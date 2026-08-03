/* Phase 0 MCAN controller probe. No external transceiver or CAN bus required. */
#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#include "board.h"
#include "hpm_mcan_drv.h"

#define PROBE_MAGIC_RUNNING (0x4D43414EU) /* "MCAN" */
#define PROBE_MAGIC_DONE    (0x50415353U) /* "PASS" */
#define PROBE_MAGIC_FAILED  (0x4641494CU) /* "FAIL" */
#define PROBE_CASES_PER_MODE (2U)

#define PROBE_FLAG_CLASSIC_STD (1U << 0)
#define PROBE_FLAG_CLASSIC_EXT (1U << 1)
#define PROBE_FLAG_FD_STD      (1U << 2)
#define PROBE_FLAG_FD_EXT      (1U << 3)

typedef struct {
    uint32_t base;
    uint32_t source_clock_hz;
    int32_t msg_ram_status;
    int32_t classic_init_status;
    int32_t fd_init_status;
    uint32_t passed_flags;
    uint32_t failed_flags;
    uint32_t frames_passed;
    uint32_t frames_failed;
} mcan_channel_probe_result_t;

typedef struct {
    uint32_t magic;
    uint32_t version;
    uint32_t channels_tested;
    uint32_t channels_passed;
    mcan_channel_probe_result_t channel[2];
} mcan_probe_result_t;

volatile mcan_probe_result_t g_mcan_probe_result;

#if defined(MCAN_SOC_MSG_BUF_IN_AHB_RAM) && (MCAN_SOC_MSG_BUF_IN_AHB_RAM == 1)
ATTR_PLACE_AT(".ahb_sram") uint32_t g_mcan0_msg_buf[MCAN_MSG_BUF_SIZE_IN_WORDS];
ATTR_PLACE_AT(".ahb_sram") uint32_t g_mcan2_msg_buf[MCAN_MSG_BUF_SIZE_IN_WORDS];
#endif

static bool frame_matches(const mcan_tx_frame_t *tx, const mcan_rx_message_t *rx)
{
    uint32_t size = mcan_get_message_size_from_dlc(rx->dlc);
    if ((tx->dlc != rx->dlc) || (tx->use_ext_id != rx->use_ext_id) ||
        (tx->rtr != rx->rtr) || (tx->canfd_frame != rx->canfd_frame)) {
        return false;
    }
    if (tx->use_ext_id ? (tx->ext_id != rx->ext_id) : (tx->std_id != rx->std_id)) {
        return false;
    }
    for (uint32_t i = 0; i < size; ++i) {
        if (tx->data_8[i] != rx->data_8[i]) {
            return false;
        }
    }
    return true;
}

static bool run_frame(MCAN_Type *base, bool canfd, bool extended)
{
    mcan_tx_frame_t tx;
    mcan_rx_message_t rx;
    memset(&tx, 0, sizeof(tx));
    memset(&rx, 0, sizeof(rx));

    tx.use_ext_id = extended;
    tx.std_id = 0x321U;
    tx.ext_id = 0x18DAF110U;
    tx.dlc = canfd ? MCAN_MSG_DLC_64_BYTES : MCAN_MSG_DLC_8_BYTES;
    tx.canfd_frame = canfd;
    tx.bitrate_switch = canfd;
    const uint32_t size = canfd ? 64U : 8U;
    for (uint32_t i = 0; i < size; ++i) {
        tx.data_8[i] = (uint8_t)(0xA5U ^ i ^ (extended ? 0x3CU : 0U));
    }

    if (mcan_transmit_blocking(base, &tx) != status_success) {
        return false;
    }
    if (mcan_receive_from_fifo_blocking(base, 0U, &rx) != status_success) {
        return false;
    }
    return frame_matches(&tx, &rx);
}

static bool run_mode(MCAN_Type *base, uint32_t source_clock_hz, bool canfd,
                     mcan_channel_probe_result_t *result)
{
    mcan_config_t config;
    mcan_get_default_config(base, &config);
    config.mode = mcan_mode_loopback_internal;
    config.enable_canfd = canfd;
    mcan_get_default_ram_config(base, &config.ram_config, canfd);

    hpm_stat_t status = mcan_init(base, &config, source_clock_hz);
    if (canfd) {
        result->fd_init_status = status;
    } else {
        result->classic_init_status = status;
    }
    if (status != status_success) {
        return false;
    }

    const uint32_t std_flag = canfd ? PROBE_FLAG_FD_STD : PROBE_FLAG_CLASSIC_STD;
    const uint32_t ext_flag = canfd ? PROBE_FLAG_FD_EXT : PROBE_FLAG_CLASSIC_EXT;
    bool std_ok = run_frame(base, canfd, false);
    bool ext_ok = run_frame(base, canfd, true);
    result->passed_flags |= std_ok ? std_flag : 0U;
    result->passed_flags |= ext_ok ? ext_flag : 0U;
    result->failed_flags |= std_ok ? 0U : std_flag;
    result->failed_flags |= ext_ok ? 0U : ext_flag;
    result->frames_passed += (uint32_t)std_ok + (uint32_t)ext_ok;
    result->frames_failed += (uint32_t)!std_ok + (uint32_t)!ext_ok;
    mcan_deinit(base);
    return std_ok && ext_ok;
}

static bool run_channel(MCAN_Type *base, uint32_t *msg_buf,
                        mcan_channel_probe_result_t *result)
{
    result->base = (uint32_t)base;
    result->source_clock_hz = board_init_can_clock(base);

#if defined(MCAN_SOC_MSG_BUF_IN_AHB_RAM) && (MCAN_SOC_MSG_BUF_IN_AHB_RAM == 1)
    mcan_msg_buf_attr_t attr = {(uint32_t)msg_buf,
                                MCAN_MSG_BUF_SIZE_IN_WORDS * sizeof(uint32_t)};
    result->msg_ram_status = mcan_set_msg_buf_attr(base, &attr);
#else
    (void)msg_buf;
    result->msg_ram_status = status_success;
#endif
    if ((result->source_clock_hz == 0U) ||
        (result->msg_ram_status != status_success)) {
        return false;
    }

    bool classic_ok = run_mode(base, result->source_clock_hz, false, result);
    bool fd_ok = run_mode(base, result->source_clock_hz, true, result);
    return classic_ok && fd_ok &&
           (result->frames_passed == (2U * PROBE_CASES_PER_MODE));
}

int main(void)
{
    board_init();
    memset((void *)&g_mcan_probe_result, 0, sizeof(g_mcan_probe_result));
    g_mcan_probe_result.magic = PROBE_MAGIC_RUNNING;
    g_mcan_probe_result.version = 1U;

    bool can0_ok = run_channel(HPM_MCAN0, g_mcan0_msg_buf,
                               (mcan_channel_probe_result_t *)&g_mcan_probe_result.channel[0]);
    g_mcan_probe_result.channels_tested++;
    g_mcan_probe_result.channels_passed += (uint32_t)can0_ok;

    bool can2_ok = run_channel(HPM_MCAN2, g_mcan2_msg_buf,
                               (mcan_channel_probe_result_t *)&g_mcan_probe_result.channel[1]);
    g_mcan_probe_result.channels_tested++;
    g_mcan_probe_result.channels_passed += (uint32_t)can2_ok;

    g_mcan_probe_result.magic = (can0_ok && can2_ok) ? PROBE_MAGIC_DONE : PROBE_MAGIC_FAILED;
    while (1) {
        __asm volatile("nop");
    }
}
