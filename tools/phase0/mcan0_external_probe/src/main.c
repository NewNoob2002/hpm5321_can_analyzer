/* MCAN0 external Classic CAN safety probe: listen-only or bounded TX build. */
#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#include "board.h"
#include "hpm_gpiom_drv.h"
#include "hpm_mcan_drv.h"

#ifndef MCAN0_ACTIVE_TX
#define MCAN0_ACTIVE_TX (0)
#endif
#ifndef MCAN0_REQUIRE_RX
#define MCAN0_REQUIRE_RX (0)
#endif
#ifndef MCAN0_ACK_RX
#define MCAN0_ACK_RX (0)
#endif

#if MCAN0_ACK_RX && (MCAN0_ACTIVE_TX || !MCAN0_REQUIRE_RX)
#error "MCAN0_ACK_RX is only valid for a receive-required, software-zero-TX build"
#endif

#define RESULT_MAGIC_RUNNING (0x52554E21U) /* RUN! */
#define RESULT_MAGIC_DONE    (0x444F4E45U) /* DONE */
#define RESULT_MAGIC_FAILED  (0x4641494CU) /* FAIL */
#define TEST_BITRATE         (500000U)
#define TEST_STD_ID          (0x123U)
#define TEST_DLC             (8U)
#define LISTEN_WINDOW_MS     (3000U)
#define RX_PROOF_TIMEOUT_MS  (3600000U)
#define TX_FRAME_COUNT       (100U)
#define TX_PERIOD_MS         (10U)
#define RX_PROOF_STD_ID      (0x321U)
#define TX_ARM_TOKEN         (0x41524D21U) /* ARM! */
#define PROBE_RESULT_ABI_VERSION (5U)
#define CLEANUP_INIT_TIMEOUT_MS (10U)
#define ARM_FAULT_IR_MASK \
    (MCAN_IR_ARA_MASK | MCAN_IR_WDI_MASK | MCAN_IR_BO_MASK | \
     MCAN_IR_EW_MASK | MCAN_IR_EP_MASK | MCAN_IR_ELO_MASK | \
     MCAN_IR_BEU_MASK | MCAN_IR_BEC_MASK | MCAN_IR_MRAF_MASK | \
     MCAN_IR_RF0L_MASK | MCAN_IR_RF1L_MASK)

typedef struct {
    uint32_t magic;
    uint32_t version;
    uint32_t active_tx_build;
    uint32_t run_nonce;
    uint32_t source_clock_hz;
    uint32_t bitrate;
    int32_t msg_ram_status;
    int32_t init_status;
    uint32_t rx_frames;
    uint32_t rx_expected_frames;
    uint32_t tx_attempted;
    uint32_t tx_succeeded;
    int32_t last_tx_status;
    uint32_t last_rx_id;
    uint32_t last_rx_dlc;
    uint8_t last_rx_data[8];
    uint32_t raw_psr;
    uint32_t raw_ecr;
    uint32_t raw_cccr;
    uint32_t raw_ir;
    uint32_t tx_error_count;
    uint32_t rx_error_count;
    uint32_t error_logging_count;
    uint32_t bus_off;
    uint32_t warning;
    uint32_t error_passive;
    uint32_t cleanup_completed;
    uint32_t post_cleanup_cccr;
    uint32_t post_cleanup_gpiob_oe;
    uint32_t post_cleanup_pb00_gpiom;
    uint32_t post_cleanup_pb01_gpiom;
    uint32_t post_cleanup_pb00_func_ctl;
    uint32_t post_cleanup_pb01_func_ctl;
} mcan0_external_probe_result_t;

volatile mcan0_external_probe_result_t g_mcan0_external_result;
/* A debugger must write TX_ARM_TOKEN after every reset. Startup/BSS clearing
 * guarantees that a reset cannot replay the bounded transmit sequence. */
volatile uint32_t g_mcan0_tx_arm_token;
/* The debugger must set a nonzero 16-bit nonce before ARM. It is copied into
 * every CAN payload and the terminal result, binding target and adapter logs. */
volatile uint32_t g_mcan0_tx_run_nonce;

#if defined(MCAN_SOC_MSG_BUF_IN_AHB_RAM) && (MCAN_SOC_MSG_BUF_IN_AHB_RAM == 1)
ATTR_PLACE_AT(".ahb_sram") uint32_t g_mcan0_external_msg_buf[MCAN_MSG_BUF_SIZE_IN_WORDS];
#endif

static void capture_status(void)
{
    /* ECR.CEL is read-to-clear. Read ECR exactly once and derive both the raw
     * snapshot and decoded fields from that same value. */
    uint32_t ecr = HPM_MCAN0->ECR;
    uint32_t psr = HPM_MCAN0->PSR;
    g_mcan0_external_result.raw_psr = psr;
    g_mcan0_external_result.raw_ecr = ecr;
    g_mcan0_external_result.raw_cccr = HPM_MCAN0->CCCR;
    g_mcan0_external_result.raw_ir = HPM_MCAN0->IR;
    g_mcan0_external_result.tx_error_count = MCAN_ECR_TEC_GET(ecr);
    g_mcan0_external_result.rx_error_count = MCAN_ECR_REC_GET(ecr);
    g_mcan0_external_result.error_logging_count += MCAN_ECR_CEL_GET(ecr);
    g_mcan0_external_result.bus_off = MCAN_PSR_BO_GET(psr);
    g_mcan0_external_result.warning = MCAN_PSR_EW_GET(psr);
    g_mcan0_external_result.error_passive = MCAN_PSR_EP_GET(psr);
}

static bool status_is_error_free(void)
{
    return g_mcan0_external_result.bus_off == 0U &&
           g_mcan0_external_result.warning == 0U &&
           g_mcan0_external_result.error_passive == 0U &&
           g_mcan0_external_result.error_logging_count == 0U;
}

static bool status_is_safe_listen_only(void)
{
    return status_is_error_free() &&
           MCAN_CCCR_INIT_GET(g_mcan0_external_result.raw_cccr) == 0U &&
           MCAN_CCCR_MON_GET(g_mcan0_external_result.raw_cccr) != 0U &&
           (g_mcan0_external_result.raw_ir & ARM_FAULT_IR_MASK) == 0U;
}

static void drain_rx_fifo(void)
{
    mcan_rx_message_t rx;
    while (mcan_get_rxfifo_fill_level(HPM_MCAN0, 0U) > 0U) {
        memset(&rx, 0, sizeof(rx));
        if (mcan_read_rxfifo(HPM_MCAN0, 0U, &rx) != status_success) {
            break;
        }
        g_mcan0_external_result.rx_frames++;
        g_mcan0_external_result.last_rx_id = rx.use_ext_id ? rx.ext_id : rx.std_id;
        g_mcan0_external_result.last_rx_dlc = rx.dlc;
        uint32_t size = mcan_get_message_size_from_dlc(rx.dlc);
        if (size > sizeof(g_mcan0_external_result.last_rx_data)) {
            size = sizeof(g_mcan0_external_result.last_rx_data);
        }
        memcpy((void *)g_mcan0_external_result.last_rx_data, rx.data_8, size);
        static const uint8_t expected_data[8] = {
            0x48U, 0x50U, 0x4DU, 0x52U, 0x00U, 0x00U, 0x00U, 0x01U,
        };
        if (!rx.use_ext_id && !rx.canfd_frame && !rx.rtr &&
            rx.std_id == RX_PROOF_STD_ID && rx.dlc == TEST_DLC &&
            size == sizeof(expected_data) &&
            memcmp(rx.data_8, expected_data, sizeof(expected_data)) == 0) {
            g_mcan0_external_result.rx_expected_frames++;
        }
    }
}

static bool init_mcan0(mcan_node_mode_t mode)
{
    g_mcan0_external_result.source_clock_hz = board_init_can_clock(HPM_MCAN0);
#if defined(MCAN_SOC_MSG_BUF_IN_AHB_RAM) && (MCAN_SOC_MSG_BUF_IN_AHB_RAM == 1)
    mcan_msg_buf_attr_t attr = {
        (uint32_t)g_mcan0_external_msg_buf,
        sizeof(g_mcan0_external_msg_buf),
    };
    g_mcan0_external_result.msg_ram_status = mcan_set_msg_buf_attr(HPM_MCAN0, &attr);
#else
    g_mcan0_external_result.msg_ram_status = status_success;
#endif
    if (g_mcan0_external_result.msg_ram_status != status_success) {
        return false;
    }

    mcan_config_t config;
    mcan_get_default_config(HPM_MCAN0, &config);
    config.baudrate = TEST_BITRATE;
    /* ACK_RX uses normal controller mode solely so hardware can acknowledge a
     * valid incoming frame. The application never calls a transmit API unless
     * MCAN0_ACTIVE_TX is set. */
    config.mode = mode;
    config.enable_canfd = false;
    config.disable_auto_retransmission = true;
    g_mcan0_external_result.init_status =
        mcan_init(HPM_MCAN0, &config, g_mcan0_external_result.source_clock_hz);
    if (g_mcan0_external_result.init_status != status_success) {
        return false;
    }

    /* Connect TXD/RXD only after the controller has entered the requested
     * safe mode. STB is hardware-low on this board, so pinmux order is the
     * firmware-controlled containment boundary. */
    board_init_can(HPM_MCAN0);
    return true;
}

static bool run_listen_only(void)
{
    const uint32_t timeout_ms = MCAN0_REQUIRE_RX ? RX_PROOF_TIMEOUT_MS : LISTEN_WINDOW_MS;
    for (uint32_t elapsed = 0; elapsed < timeout_ms; ++elapsed) {
        drain_rx_fifo();
        capture_status();
        if (!status_is_error_free()) {
            return false;
        }
        if (MCAN0_REQUIRE_RX &&
            g_mcan0_external_result.rx_expected_frames > 0U) {
            break;
        }
        board_delay_ms(1U);
    }
    drain_rx_fifo();
    capture_status();
    bool receive_requirement_met =
        !MCAN0_REQUIRE_RX ||
        (g_mcan0_external_result.rx_expected_frames > 0U);
    return receive_requirement_met &&
           (g_mcan0_external_result.bus_off == 0U) &&
           (g_mcan0_external_result.warning == 0U) &&
           (g_mcan0_external_result.error_passive == 0U) &&
           (g_mcan0_external_result.error_logging_count == 0U);
}

static bool wait_for_tx_arm(void)
{
    while (g_mcan0_tx_arm_token != TX_ARM_TOKEN ||
           g_mcan0_tx_run_nonce == 0U || g_mcan0_tx_run_nonce > UINT16_MAX) {
        capture_status();
        if (!status_is_safe_listen_only()) {
            return false;
        }
        board_delay_ms(1U);
    }
    capture_status();
    if (!status_is_safe_listen_only()) {
        return false;
    }
    /* Consume before enabling normal mode. A reset from this point clears the
     * token and therefore returns to the disarmed wait state. */
    g_mcan0_tx_arm_token = 0U;
    g_mcan0_external_result.run_nonce = g_mcan0_tx_run_nonce;
    return true;
}

static void invalidate_cleanup_snapshot(void)
{
    g_mcan0_external_result.cleanup_completed = 0U;
    g_mcan0_external_result.post_cleanup_cccr = 0U;
    g_mcan0_external_result.post_cleanup_gpiob_oe = 0U;
    g_mcan0_external_result.post_cleanup_pb00_gpiom = 0U;
    g_mcan0_external_result.post_cleanup_pb01_gpiom = 0U;
    g_mcan0_external_result.post_cleanup_pb00_func_ctl = 0U;
    g_mcan0_external_result.post_cleanup_pb01_func_ctl = 0U;
}

static bool wait_for_mcan_init(void)
{
    for (uint32_t elapsed_ms = 0U; elapsed_ms < CLEANUP_INIT_TIMEOUT_MS;
         ++elapsed_ms) {
        if (MCAN_CCCR_INIT_GET(HPM_MCAN0->CCCR) != 0U) {
            return true;
        }
        board_delay_ms(1U);
    }
    return MCAN_CCCR_INIT_GET(HPM_MCAN0->CCCR) != 0U;
}

static bool disarm_mcan0(void)
{
    mcan_enter_init_mode(HPM_MCAN0);
    bool init_acknowledged = wait_for_mcan_init();
    if (init_acknowledged) {
        /* The SDK deinit writes protected configuration registers. Invoke it
         * only after INIT acknowledgement has been observed. */
        mcan_deinit(HPM_MCAN0);
    }
    capture_status();
    init_mcan_safe_gpio_inputs();
    g_mcan0_tx_arm_token = 0U;
    g_mcan0_external_result.post_cleanup_cccr = HPM_MCAN0->CCCR;
    g_mcan0_external_result.post_cleanup_gpiob_oe =
        HPM_GPIO0->OE[GPIO_OE_GPIOB].VALUE;
    g_mcan0_external_result.post_cleanup_pb00_gpiom =
        HPM_GPIOM->ASSIGN[GPIO_OE_GPIOB].PIN[0U];
    g_mcan0_external_result.post_cleanup_pb01_gpiom =
        HPM_GPIOM->ASSIGN[GPIO_OE_GPIOB].PIN[1U];
    g_mcan0_external_result.post_cleanup_pb00_func_ctl =
        HPM_IOC->PAD[IOC_PAD_PB00].FUNC_CTL;
    g_mcan0_external_result.post_cleanup_pb01_func_ctl =
        HPM_IOC->PAD[IOC_PAD_PB01].FUNC_CTL;
    bool cleanup_ok =
        init_acknowledged &&
        MCAN_CCCR_INIT_GET(g_mcan0_external_result.post_cleanup_cccr) != 0U &&
        (g_mcan0_external_result.post_cleanup_gpiob_oe & 0x3U) == 0U &&
        GPIOM_ASSIGN_PIN_SELECT_GET(g_mcan0_external_result.post_cleanup_pb00_gpiom) ==
            gpiom_soc_gpio0 &&
        GPIOM_ASSIGN_PIN_SELECT_GET(g_mcan0_external_result.post_cleanup_pb01_gpiom) ==
            gpiom_soc_gpio0 &&
        g_mcan0_external_result.post_cleanup_pb00_func_ctl ==
            IOC_PB00_FUNC_CTL_GPIO_B_00 &&
        g_mcan0_external_result.post_cleanup_pb01_func_ctl ==
            IOC_PB01_FUNC_CTL_GPIO_B_01 &&
        g_mcan0_external_result.error_logging_count == 0U;
    g_mcan0_external_result.cleanup_completed = cleanup_ok ? 1U : 0U;
    return cleanup_ok;
}

static bool run_bounded_tx(void)
{
    mcan_tx_frame_t tx;
    memset(&tx, 0, sizeof(tx));
    tx.std_id = TEST_STD_ID;
    tx.dlc = TEST_DLC;
    for (uint32_t sequence = 0; sequence < TX_FRAME_COUNT; ++sequence) {
        tx.data_8[0] = 0x48U; /* H */
        tx.data_8[1] = 0x50U; /* P */
        tx.data_8[2] = (uint8_t)(g_mcan0_external_result.run_nonce >> 8U);
        tx.data_8[3] = (uint8_t)g_mcan0_external_result.run_nonce;
        tx.data_8[4] = (uint8_t)(sequence >> 24U);
        tx.data_8[5] = (uint8_t)(sequence >> 16U);
        tx.data_8[6] = (uint8_t)(sequence >> 8U);
        tx.data_8[7] = (uint8_t)sequence;
        g_mcan0_external_result.tx_attempted++;
        hpm_stat_t status = mcan_transmit_blocking(HPM_MCAN0, &tx);
        g_mcan0_external_result.last_tx_status = status;
        if (status != status_success) {
            capture_status();
            return false;
        }
        g_mcan0_external_result.tx_succeeded++;
        drain_rx_fifo();
        board_delay_ms(TX_PERIOD_MS);
    }
    capture_status();
    return (g_mcan0_external_result.tx_succeeded == TX_FRAME_COUNT) &&
           (g_mcan0_external_result.bus_off == 0U) &&
           (g_mcan0_external_result.warning == 0U) &&
           (g_mcan0_external_result.error_passive == 0U) &&
           (g_mcan0_external_result.error_logging_count == 0U);
}

int main(void)
{
    board_init();
    memset((void *)&g_mcan0_external_result, 0, sizeof(g_mcan0_external_result));
    g_mcan0_external_result.magic = RESULT_MAGIC_RUNNING;
    g_mcan0_external_result.version = PROBE_RESULT_ABI_VERSION;
    g_mcan0_external_result.active_tx_build = MCAN0_ACTIVE_TX;
    g_mcan0_external_result.bitrate = TEST_BITRATE;

    bool ok;
    if (MCAN0_ACTIVE_TX) {
        ok = init_mcan0(mcan_mode_listen_only) && wait_for_tx_arm();
        if (ok) {
            ok = disarm_mcan0();
            if (ok) {
                invalidate_cleanup_snapshot();
                ok = init_mcan0(mcan_mode_normal) && run_bounded_tx();
            }
        }
        ok = disarm_mcan0() && ok;
    } else {
        mcan_node_mode_t mode = MCAN0_ACK_RX ? mcan_mode_normal : mcan_mode_listen_only;
        ok = init_mcan0(mode) && run_listen_only();
        ok = disarm_mcan0() && ok;
    }
    g_mcan0_external_result.magic = ok ? RESULT_MAGIC_DONE : RESULT_MAGIC_FAILED;
    while (1) {
        __asm volatile("nop");
    }
}
