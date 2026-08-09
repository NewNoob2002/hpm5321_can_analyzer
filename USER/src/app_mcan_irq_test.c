#include "app_mcan_irq_test.h"

#include <string.h>

#include "FreeRTOS.h"
#include "app_irq_contract.h"
#include "board.h"
#include "hpm_interrupt.h"
#include "hpm_mcan_drv.h"
#include "queue.h"
#include "task.h"

#define APP_MCAN_IRQ_TEST_STACK_WORDS (configMINIMAL_STACK_SIZE + 256U)
#define APP_MCAN_IRQ_TEST_QUEUE_LENGTH (4U)
#define APP_MCAN_IRQ_TEST_TASK_PRIORITY (3U)
#define APP_MCAN_IRQ_TEST_RECEIVE_TIMEOUT_MS (1000U)
#define APP_MCAN_IRQ_TEST_ID_BASE (0x300U)
#define APP_MCAN_IRQ_TEST_FAULT_MASK                                      \
    (MCAN_EVENT_ERROR | MCAN_INT_ACCESS_TO_RESERVED_ADDR |               \
     MCAN_INT_WATCHDOG_INT | MCAN_INT_ERROR_LOGGING_OVERFLOW |           \
     MCAN_INT_BIT_ERROR_CORRECTED | MCAN_INT_TIMEOUT_OCCURRED |          \
     MCAN_INT_MSG_RAM_ACCESS_FAILURE | MCAN_INT_TX_EVT_FIFO_EVT_LOST |   \
     MCAN_INT_TX_EVT_FIFO_FULL | MCAN_INT_RXFIFO1_MSG_LOST |             \
     MCAN_INT_RXFIFO1_FULL | MCAN_INT_RXFIFO0_MSG_LOST |                 \
     MCAN_INT_RXFIFO0_FULL)

APP_IRQ_ASSERT_FREERTOS_API_PRIORITY(APP_MCAN_IRQ_TEST_ISR_PRIORITY);

static StaticTask_t mcan_test_task_tcb;
static StackType_t mcan_test_task_stack[APP_MCAN_IRQ_TEST_STACK_WORDS];
static StaticQueue_t mcan_test_queue_control;
static uint8_t mcan_test_queue_storage[
    APP_MCAN_IRQ_TEST_QUEUE_LENGTH * sizeof(mcan_rx_message_t)];
static QueueHandle_t mcan_test_queue;

#if defined(MCAN_SOC_MSG_BUF_IN_AHB_RAM) && (MCAN_SOC_MSG_BUF_IN_AHB_RAM == 1)
ATTR_PLACE_AT(".ahb_sram")
static uint32_t mcan0_msg_buf[MCAN_MSG_BUF_SIZE_IN_WORDS];
#endif

volatile app_mcan_irq_test_state_t g_app_mcan_irq_test_state = {
    .magic = APP_MCAN_IRQ_TEST_MAGIC_RUNNING,
    .version = APP_MCAN_IRQ_TEST_VERSION,
    .message_ram_status = status_success,
    .init_status = status_fail,
    .last_transmit_status = status_fail,
    .cleanup_status = status_fail,
};

static void fill_frame(mcan_tx_frame_t *frame, uint32_t sequence)
{
    memset(frame, 0, sizeof(*frame));
    frame->std_id = APP_MCAN_IRQ_TEST_ID_BASE + (sequence & 0x3FFU);
    frame->dlc = MCAN_MSG_DLC_8_BYTES;
    frame->data_32[0] = sequence;
    frame->data_32[1] = sequence ^ UINT32_C(0xA55A3CC3);
}

static bool frame_matches(const mcan_tx_frame_t *tx,
                          const mcan_rx_message_t *rx)
{
    return rx->use_ext_id == 0U && rx->rtr == 0U &&
           rx->canfd_frame == 0U && rx->std_id == tx->std_id &&
           rx->dlc == tx->dlc && rx->data_32[0] == tx->data_32[0] &&
           rx->data_32[1] == tx->data_32[1];
}

static void capture_terminal_diagnostics(void)
{
    const uint32_t error_count = HPM_MCAN0->ECR;

    g_app_mcan_irq_test_state.terminal_fault_flags =
        mcan_get_interrupt_flags(HPM_MCAN0) & APP_MCAN_IRQ_TEST_FAULT_MASK;
    g_app_mcan_irq_test_state.terminal_protocol_status = HPM_MCAN0->PSR;
    g_app_mcan_irq_test_state.terminal_error_count = error_count;
    g_app_mcan_irq_test_state.tx_error_count = MCAN_ECR_TEC_GET(error_count);
    g_app_mcan_irq_test_state.rx_error_count = MCAN_ECR_REC_GET(error_count);
    g_app_mcan_irq_test_state.error_logging_count = MCAN_ECR_CEL_GET(error_count);
}

static bool stop_controller(void)
{
    intc_m_disable_irq(BOARD_CAN0_IRQn);
    mcan_disable_interrupts(HPM_MCAN0, UINT32_MAX);
    g_app_mcan_irq_test_state.cleanup_status =
        mcan_begin_reconfig(HPM_MCAN0);
    if (g_app_mcan_irq_test_state.cleanup_status == status_success) {
        mcan_deinit(HPM_MCAN0);
    }
    g_app_mcan_irq_test_state.post_cleanup_cccr = HPM_MCAN0->CCCR;
    g_app_mcan_irq_test_state.cleanup_completed =
        g_app_mcan_irq_test_state.cleanup_status == status_success &&
                MCAN_CCCR_INIT_GET(
                    g_app_mcan_irq_test_state.post_cleanup_cccr) != 0U
            ? 1U
            : 0U;
    return g_app_mcan_irq_test_state.cleanup_completed != 0U;
}

static uint32_t read_irq_priority(uint32_t irq)
{
    const uintptr_t address =
        HPM_PLIC_BASE + HPM_PLIC_PRIORITY_OFFSET +
        ((irq - 1U) << HPM_PLIC_PRIORITY_SHIFT_PER_SOURCE);
    return *(volatile const uint32_t *)address;
}

SDK_DECLARE_EXT_ISR_M(BOARD_CAN0_IRQn, app_mcan0_irq_test_isr)
void app_mcan0_irq_test_isr(void)
{
    BaseType_t higher_priority_task_woken = pdFALSE;
    mcan_rx_message_t received;
    const uint32_t flags = mcan_get_interrupt_flags(HPM_MCAN0);

    g_app_mcan_irq_test_state.interrupt_count++;
    g_app_mcan_irq_test_state.interrupt_flags |= flags;
    g_app_mcan_irq_test_state.error_interrupt_flags |=
        flags & APP_MCAN_IRQ_TEST_FAULT_MASK;

    if ((flags & MCAN_INT_RXFIFO0_NEW_MSG) != 0U &&
        mcan_read_rxfifo(HPM_MCAN0, 0U, &received) == status_success) {
        if (xQueueSendFromISR(mcan_test_queue, &received,
                              &higher_priority_task_woken) == pdPASS) {
            g_app_mcan_irq_test_state.queue_send_count++;
        } else {
            g_app_mcan_irq_test_state.queue_drops++;
        }
    }

    mcan_clear_interrupt_flags(HPM_MCAN0, flags);
    portYIELD_FROM_ISR(higher_priority_task_woken);
}

static bool configure_controller(void)
{
    mcan_config_t config;
    const uint32_t source_clock_hz = board_init_can_clock(HPM_MCAN0);

#if defined(MCAN_SOC_MSG_BUF_IN_AHB_RAM) && (MCAN_SOC_MSG_BUF_IN_AHB_RAM == 1)
    const mcan_msg_buf_attr_t message_ram = {
        (uint32_t)mcan0_msg_buf,
        sizeof(mcan0_msg_buf),
    };
    g_app_mcan_irq_test_state.message_ram_status =
        mcan_set_msg_buf_attr(HPM_MCAN0, &message_ram);
#endif
    if (source_clock_hz == 0U ||
        g_app_mcan_irq_test_state.message_ram_status != status_success) {
        return false;
    }

    mcan_get_default_config(HPM_MCAN0, &config);
    config.mode = mcan_mode_loopback_internal;
    config.enable_canfd = false;
    config.interrupt_mask = MCAN_INT_RXFIFO0_NEW_MSG |
                            APP_MCAN_IRQ_TEST_FAULT_MASK;
    g_app_mcan_irq_test_state.init_status =
        mcan_init(HPM_MCAN0, &config, source_clock_hz);
    if (g_app_mcan_irq_test_state.init_status != status_success) {
        return false;
    }

    intc_m_enable_irq_with_priority(BOARD_CAN0_IRQn,
                                    APP_MCAN_IRQ_TEST_ISR_PRIORITY);
    g_app_mcan_irq_test_state.irq_priority =
        read_irq_priority(BOARD_CAN0_IRQn);
    return g_app_mcan_irq_test_state.irq_priority ==
           APP_MCAN_IRQ_TEST_ISR_PRIORITY;
}

static void mcan_test_task(void *context)
{
    mcan_tx_frame_t transmitted;
    mcan_rx_message_t received;
    uint32_t sequence;
    bool passed = configure_controller();
    const bool controller_initialized =
        g_app_mcan_irq_test_state.init_status == status_success;
    (void)context;

    for (sequence = 0U;
         passed && sequence < APP_MCAN_IRQ_TEST_FRAME_COUNT;
         sequence++) {
        uint32_t fifo_index;

        fill_frame(&transmitted, sequence);
        g_app_mcan_irq_test_state.last_transmit_status =
            mcan_transmit_via_txfifo_nonblocking(
                HPM_MCAN0, &transmitted, &fifo_index);
        if (g_app_mcan_irq_test_state.last_transmit_status != status_success) {
            passed = false;
            break;
        }
        g_app_mcan_irq_test_state.frames_submitted++;

        if (xQueueReceive(mcan_test_queue, &received,
                          pdMS_TO_TICKS(APP_MCAN_IRQ_TEST_RECEIVE_TIMEOUT_MS)) !=
            pdPASS) {
            g_app_mcan_irq_test_state.receive_timeouts++;
            passed = false;
            break;
        }
        g_app_mcan_irq_test_state.frames_received++;
        if (frame_matches(&transmitted, &received)) {
            g_app_mcan_irq_test_state.frames_matched++;
        } else {
            g_app_mcan_irq_test_state.frame_mismatches++;
            passed = false;
        }
    }

    g_app_mcan_irq_test_state.receiver_stack_high_watermark =
        uxTaskGetStackHighWaterMark(NULL);
    if (controller_initialized) {
        capture_terminal_diagnostics();
        passed = stop_controller() && passed;
    }
    if (g_app_mcan_irq_test_state.error_interrupt_flags != 0U ||
        g_app_mcan_irq_test_state.terminal_fault_flags != 0U ||
        g_app_mcan_irq_test_state.tx_error_count != 0U ||
        g_app_mcan_irq_test_state.rx_error_count != 0U ||
        g_app_mcan_irq_test_state.error_logging_count != 0U ||
        g_app_mcan_irq_test_state.queue_drops != 0U ||
        g_app_mcan_irq_test_state.frames_matched !=
            APP_MCAN_IRQ_TEST_FRAME_COUNT) {
        passed = false;
    }
    g_app_mcan_irq_test_state.magic =
        passed ? APP_MCAN_IRQ_TEST_MAGIC_DONE : APP_MCAN_IRQ_TEST_MAGIC_FAILED;
    vTaskSuspend(NULL);
}

bool app_mcan_irq_test_start(void)
{
    mcan_test_queue = xQueueCreateStatic(
        APP_MCAN_IRQ_TEST_QUEUE_LENGTH, sizeof(mcan_rx_message_t),
        mcan_test_queue_storage, &mcan_test_queue_control);
    if (mcan_test_queue == NULL) {
        return false;
    }

    return xTaskCreateStatic(
               mcan_test_task, "mcan_irq_test", APP_MCAN_IRQ_TEST_STACK_WORDS,
               NULL, APP_MCAN_IRQ_TEST_TASK_PRIORITY, mcan_test_task_stack,
               &mcan_test_task_tcb) != NULL;
}
