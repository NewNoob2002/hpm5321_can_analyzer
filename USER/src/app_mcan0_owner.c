#include "app_mcan0_owner.h"

#include <stddef.h>
#include <string.h>

#include "FreeRTOS.h"
#include "app_health.h"
#include "app_irq_contract.h"
#include "app_time.h"
#include "app_usb_owner.h"
#include "app_watchdog.h"
#include "board.h"
#include "hpm_interrupt.h"
#include "hpm_mcan_drv.h"
#include "queue.h"
#include "task.h"

#define APP_MCAN0_OWNER_STACK_WORDS (configMINIMAL_STACK_SIZE + 384U)
#define APP_MCAN0_OWNER_TASK_PRIORITY (3U)
#define APP_MCAN0_OWNER_IDLE_POLL_MS (100U)
#define APP_MCAN0_OWNER_FAULT_MASK                                      \
    (MCAN_EVENT_ERROR | MCAN_INT_ACCESS_TO_RESERVED_ADDR |             \
     MCAN_INT_WATCHDOG_INT | MCAN_INT_ERROR_LOGGING_OVERFLOW |         \
     MCAN_INT_BIT_ERROR_CORRECTED | MCAN_INT_TIMEOUT_OCCURRED |        \
     MCAN_INT_MSG_RAM_ACCESS_FAILURE | MCAN_INT_RXFIFO0_MSG_LOST |     \
     MCAN_INT_RXFIFO0_FULL)
#define APP_MCAN0_OWNER_IRQ_MASK                                        \
    (MCAN_INT_RXFIFO0_NEW_MSG | APP_MCAN0_OWNER_FAULT_MASK)

typedef enum {
    APP_MCAN0_EVENT_RX = 1,
    APP_MCAN0_EVENT_DIAGNOSTIC = 2,
} app_mcan0_event_type_t;

typedef struct {
    uint32_t type;
    uint32_t interrupt_flags;
    uint32_t protocol_status;
    uint32_t error_count;
    uint64_t timestamp_tick;
    mcan_rx_message_t frame;
} app_mcan0_event_t;

APP_IRQ_ASSERT_FREERTOS_API_PRIORITY(APP_MCAN0_OWNER_ISR_PRIORITY);
_Static_assert(sizeof(app_mcan0_diagnostics_t) ==
                   APP_MCAN0_DIAGNOSTICS_SNAPSHOT_LEN,
               "internal MCAN diagnostics snapshot size changed");
_Static_assert(offsetof(app_mcan0_diagnostics_t, snapshot_tick) == 16U,
               "internal MCAN diagnostics timestamp layout changed");
_Static_assert(offsetof(app_mcan0_diagnostics_t, rx_queue_drops) == 80U,
               "internal MCAN diagnostics drop layout changed");
_Static_assert(offsetof(app_mcan0_diagnostics_t, ring_drops) == 92U,
               "internal MCAN diagnostics wire projection layout changed");

static StaticTask_t mcan0_owner_task_tcb;
static StackType_t mcan0_owner_task_stack[APP_MCAN0_OWNER_STACK_WORDS];
static StaticQueue_t mcan0_event_queue_control;
static uint8_t mcan0_event_queue_storage[
    APP_MCAN0_OWNER_EVENT_QUEUE_LENGTH * sizeof(app_mcan0_event_t)];
static QueueHandle_t mcan0_event_queue;

static app_mcan0_owner_rx_record_t
    mcan0_rx_ring[APP_MCAN0_OWNER_RX_RING_CAPACITY];
static uint32_t mcan0_rx_ring_head;
static uint32_t mcan0_rx_ring_tail;
static uint32_t mcan0_rx_ring_count;
static app_mcan0_owner_state_edge_t
    mcan0_state_edge_ring[APP_MCAN0_OWNER_STATE_EDGE_CAPACITY];
static uint32_t mcan0_state_edge_head;
static uint32_t mcan0_state_edge_tail;
static uint32_t mcan0_state_edge_count;
static uint32_t mcan0_diagnostics_generation;
static uint32_t mcan0_error_state_flags;
static uint8_t mcan0_edge_channel_state;

#if defined(MCAN_SOC_MSG_BUF_IN_AHB_RAM) && (MCAN_SOC_MSG_BUF_IN_AHB_RAM == 1)
ATTR_PLACE_AT(".ahb_sram")
static uint32_t mcan0_msg_buf[MCAN_MSG_BUF_SIZE_IN_WORDS];
#endif

volatile app_mcan0_owner_state_t g_app_mcan0_owner_state = {
    .magic = APP_MCAN0_OWNER_MAGIC,
    .version = APP_MCAN0_OWNER_VERSION,
    .mode = APP_MCAN0_OWNER_MODE_OFFLINE,
    .message_ram_status = status_success,
    .init_status = status_fail,
};

static uint32_t read_irq_priority(uint32_t irq)
{
    const uintptr_t address =
        HPM_PLIC_BASE + HPM_PLIC_PRIORITY_OFFSET +
        ((irq - 1U) << HPM_PLIC_PRIORITY_SHIFT_PER_SOURCE);
    return *(volatile const uint32_t *)address;
}

static void update_queue_depth_from_isr(void)
{
    const uint32_t depth = (uint32_t)uxQueueMessagesWaitingFromISR(
        mcan0_event_queue);

    g_app_mcan0_owner_state.queue_count = depth;
    if (depth > g_app_mcan0_owner_state.queue_high_watermark) {
        g_app_mcan0_owner_state.queue_high_watermark = depth;
    }
}

static void update_rxfifo0_fill_from_isr(void)
{
    const uint32_t fill = mcan_get_rxfifo_fill_level(HPM_MCAN0, 0U);

    g_app_mcan0_owner_state.rxfifo0_fill_level = fill;
    if (fill > g_app_mcan0_owner_state.rxfifo0_high_watermark) {
        g_app_mcan0_owner_state.rxfifo0_high_watermark = fill;
    }
}

static void enqueue_from_isr(const app_mcan0_event_t *event,
                             BaseType_t *higher_priority_task_woken)
{
    if (xQueueSendFromISR(mcan0_event_queue, event,
                          higher_priority_task_woken) == pdPASS) {
        g_app_mcan0_owner_state.queue_send_count++;
    } else {
        g_app_mcan0_owner_state.queue_drops++;
        if (event->type == APP_MCAN0_EVENT_RX) {
            g_app_mcan0_owner_state.rx_queue_drops++;
        } else {
            g_app_mcan0_owner_state.diagnostic_queue_drops++;
        }
    }
    update_queue_depth_from_isr();
}

SDK_DECLARE_EXT_ISR_M(BOARD_CAN0_IRQn, app_mcan0_owner_isr)
void app_mcan0_owner_isr(void)
{
    BaseType_t higher_priority_task_woken = pdFALSE;
    const uint32_t flags = mcan_get_interrupt_flags(HPM_MCAN0);
    const uint32_t clear_flags = flags & ~MCAN_INT_RXFIFO0_NEW_MSG;
    uint32_t fault_protocol_status = 0U;
    uint32_t fault_error_count = 0U;
    uint64_t fault_timestamp_tick = 0U;

    if ((flags & APP_MCAN0_OWNER_FAULT_MASK) != 0U) {
        /* Capture the error state before RX FIFO draining can delay the ISR.
         * Error-passive/recovery transitions may otherwise collapse into the
         * same later task-level PSR sample under sustained traffic. */
        fault_protocol_status = HPM_MCAN0->PSR;
        fault_error_count = HPM_MCAN0->ECR;
        fault_timestamp_tick = app_time_now();
    }

    g_app_mcan0_owner_state.interrupt_count++;
    g_app_mcan0_owner_state.interrupt_flags |= flags;
    g_app_mcan0_owner_state.error_interrupt_flags |=
        flags & APP_MCAN0_OWNER_FAULT_MASK;

    if ((flags & MCAN_INT_RXFIFO0_NEW_MSG) != 0U) {
        app_mcan0_event_t event = {
            .type = APP_MCAN0_EVENT_RX,
            .interrupt_flags = flags,
        };

        update_rxfifo0_fill_from_isr();
        do {
            mcan_clear_interrupt_flags(HPM_MCAN0,
                                       MCAN_INT_RXFIFO0_NEW_MSG);
            while (mcan_read_rxfifo(HPM_MCAN0, 0U, &event.frame) ==
                   status_success) {
                event.timestamp_tick = app_time_now();
                g_app_mcan0_owner_state.frames_received++;
                enqueue_from_isr(&event, &higher_priority_task_woken);
            }
        } while (mcan_is_interrupt_flag_set(HPM_MCAN0,
                                            MCAN_INT_RXFIFO0_NEW_MSG));
        update_rxfifo0_fill_from_isr();
    }

    if ((flags & APP_MCAN0_OWNER_FAULT_MASK) != 0U) {
        const app_mcan0_event_t event = {
            .type = APP_MCAN0_EVENT_DIAGNOSTIC,
            .interrupt_flags = flags,
            .protocol_status = fault_protocol_status,
            .error_count = fault_error_count,
            .timestamp_tick = fault_timestamp_tick,
        };
        enqueue_from_isr(&event, &higher_priority_task_woken);
    }

    mcan_clear_interrupt_flags(HPM_MCAN0, clear_flags);
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
    g_app_mcan0_owner_state.message_ram_status =
        mcan_set_msg_buf_attr(HPM_MCAN0, &message_ram);
#endif
    if (source_clock_hz == 0U ||
        g_app_mcan0_owner_state.message_ram_status != status_success) {
        return false;
    }

    mcan_get_default_config(HPM_MCAN0, &config);
    config.baudrate = APP_MCAN0_OWNER_BITRATE;
    config.mode = mcan_mode_listen_only;
    config.enable_canfd = false;
    config.disable_auto_retransmission = true;
    config.ram_config.enable_std_filter = false;
    config.ram_config.std_filter_elem_count = 0U;
    config.ram_config.enable_ext_filter = false;
    config.ram_config.ext_filter_elem_count = 0U;
    config.ram_config.enable_txbuf = false;
    config.ram_config.txbuf_dedicated_txbuf_elem_count = 0U;
    config.ram_config.txbuf_fifo_or_queue_elem_count = 0U;
    config.ram_config.enable_tx_evt_fifo = false;
    config.ram_config.tx_evt_fifo_elem_count = 0U;
    config.ram_config.tx_evt_fifo_watermark = 0U;
    config.ram_config.rxfifos[0].enable = true;
    config.ram_config.rxfifos[0].elem_count =
        APP_MCAN0_OWNER_EVENT_QUEUE_LENGTH;
    config.ram_config.rxfifos[0].watermark = 1U;
    config.ram_config.rxfifos[0].operation_mode =
        MCAN_FIFO_OPERATION_MODE_BLOCKING;
    config.ram_config.rxfifos[1].enable = false;
    config.ram_config.enable_rxbuf = false;
    config.all_filters_config.std_id_filter_list.filter_elem_list = NULL;
    config.all_filters_config.std_id_filter_list.mcan_filter_elem_count = 0U;
    config.all_filters_config.ext_id_filter_list.filter_elem_list = NULL;
    config.all_filters_config.ext_id_filter_list.mcan_filter_elem_count = 0U;
    config.all_filters_config.global_filter_config
        .accept_non_matching_std_frame_option =
        MCAN_ACCEPT_NON_MATCHING_FRAME_OPTION_IN_RXFIFO0;
    config.all_filters_config.global_filter_config
        .accept_non_matching_ext_frame_option =
        MCAN_ACCEPT_NON_MATCHING_FRAME_OPTION_IN_RXFIFO0;
    config.interrupt_mask = APP_MCAN0_OWNER_IRQ_MASK;

    g_app_mcan0_owner_state.init_status =
        mcan_init(HPM_MCAN0, &config, source_clock_hz);
    if (g_app_mcan0_owner_state.init_status != status_success) {
        return false;
    }
    g_app_mcan0_owner_state.source_clock_hz = source_clock_hz;
    g_app_mcan0_owner_state.control_status = HPM_MCAN0->CCCR;
    g_app_mcan0_owner_state.nominal_bit_timing = HPM_MCAN0->NBTP;
    if ((g_app_mcan0_owner_state.control_status & MCAN_CCCR_MON_MASK) == 0U) {
        return false;
    }

    /* Pads are connected only after the controller is live in listen-only
     * mode. This preserves reset/startup TX containment. */
    board_init_can(HPM_MCAN0);
    intc_m_enable_irq_with_priority(BOARD_CAN0_IRQn,
                                    APP_MCAN0_OWNER_ISR_PRIORITY);
    g_app_mcan0_owner_state.irq_priority =
        read_irq_priority(BOARD_CAN0_IRQn);
    if (g_app_mcan0_owner_state.irq_priority !=
        APP_MCAN0_OWNER_ISR_PRIORITY) {
        return false;
    }

    g_app_mcan0_owner_state.mode = APP_MCAN0_OWNER_MODE_LISTEN_ONLY;
    g_app_mcan0_owner_state.initialized = 1U;
    g_app_mcan0_owner_state.online = 1U;
    g_app_mcan0_owner_state.tx_armed = 0U;
    mcan0_edge_channel_state = 1U;
    return true;
}

static void publish_rx(const app_mcan0_event_t *event)
{
    app_mcan0_owner_rx_record_t record;
    bool published = false;
    const uint8_t payload_length =
        mcan_get_message_size_from_dlc(event->frame.dlc);

    if (event->frame.canfd_frame != 0U ||
        payload_length > APP_MCAN0_OWNER_CLASSIC_MAX_BYTES) {
        g_app_mcan0_owner_state.invalid_frames++;
        return;
    }

    memset(&record, 0, sizeof(record));
    record.timestamp_tick = event->timestamp_tick;
    record.sequence = ++g_app_mcan0_owner_state.rx_sequence;
    record.can_id = event->frame.use_ext_id != 0U
                        ? event->frame.ext_id
                        : event->frame.std_id;
    record.dlc = event->frame.dlc;
    record.use_ext_id = event->frame.use_ext_id;
    record.rtr = event->frame.rtr;
    record.error_state_indicator = event->frame.error_state_indicator;
    if (record.rtr == 0U && payload_length != 0U) {
        memcpy(record.data, event->frame.data_8, payload_length);
    }

    taskENTER_CRITICAL();
    if (mcan0_rx_ring_count < APP_MCAN0_OWNER_RX_RING_CAPACITY) {
        mcan0_rx_ring[mcan0_rx_ring_head] = record;
        mcan0_rx_ring_head =
            (mcan0_rx_ring_head + 1U) % APP_MCAN0_OWNER_RX_RING_CAPACITY;
        mcan0_rx_ring_count++;
        g_app_mcan0_owner_state.ring_count = mcan0_rx_ring_count;
        if (mcan0_rx_ring_count >
            g_app_mcan0_owner_state.ring_high_watermark) {
            g_app_mcan0_owner_state.ring_high_watermark =
                mcan0_rx_ring_count;
        }
        g_app_mcan0_owner_state.frames_published++;
        g_app_mcan0_owner_state.last_rx_tick = record.timestamp_tick;
        published = true;
    } else {
        g_app_mcan0_owner_state.ring_drops++;
    }
    taskEXIT_CRITICAL();

    if (published && !app_health_signal_can0_rx()) {
        g_app_mcan0_owner_state.activity_signal_drops++;
    }
    if (published && !app_usb_owner_signal_can_rx()) {
        g_app_mcan0_owner_state.activity_signal_drops++;
    }
}

static void update_error_state_counters(uint32_t protocol_status)
{
    uint32_t state_flags = 0U;

    if (MCAN_PSR_EW_GET(protocol_status) != 0U) {
        state_flags |= APP_MCAN0_DIAG_STATE_WARNING;
    }
    if (MCAN_PSR_EP_GET(protocol_status) != 0U) {
        state_flags |= APP_MCAN0_DIAG_STATE_ERROR_PASSIVE;
    }
    if (MCAN_PSR_BO_GET(protocol_status) != 0U) {
        state_flags |= APP_MCAN0_DIAG_STATE_BUS_OFF;
        g_app_mcan0_owner_state.tx_armed = 0U;
    }

    if ((state_flags & APP_MCAN0_DIAG_STATE_WARNING) != 0U &&
        (mcan0_error_state_flags & APP_MCAN0_DIAG_STATE_WARNING) == 0U) {
        g_app_mcan0_owner_state.warning_count++;
    }
    if ((state_flags & APP_MCAN0_DIAG_STATE_ERROR_PASSIVE) != 0U &&
        (mcan0_error_state_flags &
         APP_MCAN0_DIAG_STATE_ERROR_PASSIVE) == 0U) {
        g_app_mcan0_owner_state.error_passive_count++;
    }
    if ((state_flags & APP_MCAN0_DIAG_STATE_BUS_OFF) != 0U &&
        (mcan0_error_state_flags & APP_MCAN0_DIAG_STATE_BUS_OFF) == 0U) {
        g_app_mcan0_owner_state.bus_off_count++;
    }
    mcan0_error_state_flags = state_flags;
}

static uint32_t state_flags_from_protocol_status(uint32_t protocol_status)
{
    uint32_t state_flags = APP_MCAN0_DIAG_STATE_INITIALIZED |
                           APP_MCAN0_DIAG_STATE_ONLINE |
                           APP_MCAN0_DIAG_STATE_LISTEN_ONLY;

    if (MCAN_PSR_EW_GET(protocol_status) != 0U) {
        state_flags |= APP_MCAN0_DIAG_STATE_WARNING;
    }
    if (MCAN_PSR_EP_GET(protocol_status) != 0U) {
        state_flags |= APP_MCAN0_DIAG_STATE_ERROR_PASSIVE;
    }
    if (MCAN_PSR_BO_GET(protocol_status) != 0U) {
        state_flags |= APP_MCAN0_DIAG_STATE_BUS_OFF;
    }
    return state_flags;
}

static uint8_t channel_state_from_flags(uint32_t state_flags)
{
    if ((state_flags & APP_MCAN0_DIAG_STATE_BUS_OFF) != 0U) {
        return 4U;
    }
    if ((state_flags & APP_MCAN0_DIAG_STATE_ERROR_PASSIVE) != 0U) {
        return 3U;
    }
    return 1U;
}

static void publish_state_edge(const app_mcan0_event_t *event)
{
    const uint32_t state_flags =
        state_flags_from_protocol_status(event->protocol_status);
    const uint8_t channel_state = channel_state_from_flags(state_flags);

    if (channel_state == mcan0_edge_channel_state) {
        return;
    }

    const app_mcan0_owner_state_edge_t edge = {
        .timestamp_tick = event->timestamp_tick,
        .state_flags = state_flags,
        .protocol_status = event->protocol_status,
        .error_count = event->error_count,
        .transmit_error_count = MCAN_ECR_TEC_GET(event->error_count),
        .receive_error_count = MCAN_ECR_REC_GET(event->error_count),
    };

    taskENTER_CRITICAL();
    if (mcan0_state_edge_count < APP_MCAN0_OWNER_STATE_EDGE_CAPACITY) {
        mcan0_state_edge_ring[mcan0_state_edge_head] = edge;
        mcan0_state_edge_head =
            (mcan0_state_edge_head + 1U) %
            APP_MCAN0_OWNER_STATE_EDGE_CAPACITY;
        mcan0_state_edge_count++;
    } else {
        /* This is diagnostic event loss, not CAN frame loss. Keep it separate
         * so the USB layer reconciles state without allocating a channel
         * sequence or reporting a CAN_RING DATA_LOSS event. */
        g_app_mcan0_owner_state.state_edge_drops++;
    }
    taskEXIT_CRITICAL();
    mcan0_edge_channel_state = channel_state;
}

static void capture_diagnostics(const app_mcan0_event_t *event)
{
    mcan_diagnostic_snapshot_t snapshot;
    uint32_t snapshot_interrupt_flags = event->interrupt_flags;

    if (mcan_get_diagnostic_snapshot(HPM_MCAN0, &snapshot) ==
        status_success) {
        snapshot_interrupt_flags |= snapshot.interrupt_flags;
    }

    taskENTER_CRITICAL();
    g_app_mcan0_owner_state.last_protocol_status = event->protocol_status;
    g_app_mcan0_owner_state.last_error_count = event->error_count;
    g_app_mcan0_owner_state.last_interrupt_snapshot =
        snapshot_interrupt_flags;
    update_error_state_counters(event->protocol_status);
    /* P3B phase 1 never initiates automatic bus-off recovery. Recovery will
     * require an explicit bounded policy once authorized TX is introduced. */
    g_app_mcan0_owner_state.automatic_recovery_attempts = 0U;
    taskEXIT_CRITICAL();
    publish_state_edge(event);
}

static void refresh_live_diagnostics(void)
{
    const uint32_t protocol_status = HPM_MCAN0->PSR;
    const uint32_t error_count = HPM_MCAN0->ECR;
    const uint32_t rxfifo0_fill =
        mcan_get_rxfifo_fill_level(HPM_MCAN0, 0U);
    const uint32_t queue_count =
        (uint32_t)uxQueueMessagesWaiting(mcan0_event_queue);

    taskENTER_CRITICAL();
    g_app_mcan0_owner_state.last_protocol_status = protocol_status;
    g_app_mcan0_owner_state.last_error_count = error_count;
    g_app_mcan0_owner_state.rxfifo0_fill_level = rxfifo0_fill;
    if (rxfifo0_fill > g_app_mcan0_owner_state.rxfifo0_high_watermark) {
        g_app_mcan0_owner_state.rxfifo0_high_watermark = rxfifo0_fill;
    }
    g_app_mcan0_owner_state.queue_count = queue_count;
    if (queue_count > g_app_mcan0_owner_state.queue_high_watermark) {
        g_app_mcan0_owner_state.queue_high_watermark = queue_count;
    }
    taskEXIT_CRITICAL();
}

static void mcan0_owner_task(void *context)
{
    app_mcan0_event_t event;
    (void)context;

    if (!configure_controller()) {
        g_app_mcan0_owner_state.mode = APP_MCAN0_OWNER_MODE_OFFLINE;
        g_app_mcan0_owner_state.online = 0U;
        vTaskSuspend(NULL);
    }

    while (1) {
        if (xQueueReceive(mcan0_event_queue, &event,
                          pdMS_TO_TICKS(APP_MCAN0_OWNER_IDLE_POLL_MS)) ==
            pdPASS) {
            if (event.type == APP_MCAN0_EVENT_RX) {
                publish_rx(&event);
            } else if (event.type == APP_MCAN0_EVENT_DIAGNOSTIC) {
                capture_diagnostics(&event);
            }
            taskENTER_CRITICAL();
            g_app_mcan0_owner_state.queue_count =
                (uint32_t)uxQueueMessagesWaiting(mcan0_event_queue);
            taskEXIT_CRITICAL();
        }
        refresh_live_diagnostics();
        g_app_mcan0_owner_state.stack_high_watermark =
            uxTaskGetStackHighWaterMark(NULL);
        app_watchdog_vote(APP_WATCHDOG_VOTER_MCAN0_OWNER);
    }
}

bool app_mcan0_owner_start(void)
{
    mcan0_event_queue = xQueueCreateStatic(
        APP_MCAN0_OWNER_EVENT_QUEUE_LENGTH, sizeof(app_mcan0_event_t),
        mcan0_event_queue_storage, &mcan0_event_queue_control);
    if (mcan0_event_queue == NULL) {
        return false;
    }

    return xTaskCreateStatic(
               mcan0_owner_task, "mcan0_owner", APP_MCAN0_OWNER_STACK_WORDS,
               NULL, APP_MCAN0_OWNER_TASK_PRIORITY, mcan0_owner_task_stack,
               &mcan0_owner_task_tcb) != NULL;
}

bool app_mcan0_owner_pop_rx(app_mcan0_owner_rx_record_t *record)
{
    bool available = false;

    if (record == NULL) {
        return false;
    }
    taskENTER_CRITICAL();
    if (mcan0_rx_ring_count != 0U) {
        *record = mcan0_rx_ring[mcan0_rx_ring_tail];
        mcan0_rx_ring_tail =
            (mcan0_rx_ring_tail + 1U) % APP_MCAN0_OWNER_RX_RING_CAPACITY;
        mcan0_rx_ring_count--;
        g_app_mcan0_owner_state.ring_count = mcan0_rx_ring_count;
        available = true;
    }
    taskEXIT_CRITICAL();
    return available;
}

bool app_mcan0_owner_rx_pending(void)
{
    bool pending;

    taskENTER_CRITICAL();
    pending = mcan0_rx_ring_count != 0U;
    taskEXIT_CRITICAL();
    return pending;
}

bool app_mcan0_owner_pop_state_edge(app_mcan0_owner_state_edge_t *edge)
{
    bool available = false;

    if (edge == NULL) {
        return false;
    }
    taskENTER_CRITICAL();
    if (mcan0_state_edge_count != 0U) {
        *edge = mcan0_state_edge_ring[mcan0_state_edge_tail];
        mcan0_state_edge_tail =
            (mcan0_state_edge_tail + 1U) %
            APP_MCAN0_OWNER_STATE_EDGE_CAPACITY;
        mcan0_state_edge_count--;
        available = true;
    }
    taskEXIT_CRITICAL();
    return available;
}

bool app_mcan0_owner_get_diagnostics(app_mcan0_diagnostics_t *snapshot)
{
    uint32_t state_flags = 0U;

    if (snapshot == NULL) {
        return false;
    }

    taskENTER_CRITICAL();
    if (g_app_mcan0_owner_state.initialized != 0U) {
        state_flags |= APP_MCAN0_DIAG_STATE_INITIALIZED;
    }
    if (g_app_mcan0_owner_state.online != 0U) {
        state_flags |= APP_MCAN0_DIAG_STATE_ONLINE;
    }
    if (g_app_mcan0_owner_state.mode ==
        APP_MCAN0_OWNER_MODE_LISTEN_ONLY) {
        state_flags |= APP_MCAN0_DIAG_STATE_LISTEN_ONLY;
    }
    if (g_app_mcan0_owner_state.tx_armed != 0U) {
        state_flags |= APP_MCAN0_DIAG_STATE_TX_ARMED;
    }
    if (MCAN_PSR_EW_GET(g_app_mcan0_owner_state.last_protocol_status) != 0U) {
        state_flags |= APP_MCAN0_DIAG_STATE_WARNING;
    }
    if (MCAN_PSR_EP_GET(g_app_mcan0_owner_state.last_protocol_status) != 0U) {
        state_flags |= APP_MCAN0_DIAG_STATE_ERROR_PASSIVE;
    }
    if (MCAN_PSR_BO_GET(g_app_mcan0_owner_state.last_protocol_status) != 0U) {
        state_flags |= APP_MCAN0_DIAG_STATE_BUS_OFF;
    }

    snapshot->version = APP_MCAN0_DIAGNOSTICS_VERSION;
    snapshot->snapshot_length = APP_MCAN0_DIAGNOSTICS_SNAPSHOT_LEN;
    snapshot->generation = ++mcan0_diagnostics_generation;
    snapshot->state_flags = state_flags;
    snapshot->snapshot_tick = app_time_now();
    snapshot->interrupt_flags = g_app_mcan0_owner_state.interrupt_flags;
    snapshot->error_interrupt_flags =
        g_app_mcan0_owner_state.error_interrupt_flags;
    snapshot->last_interrupt_flags =
        g_app_mcan0_owner_state.last_interrupt_snapshot;
    snapshot->protocol_status =
        g_app_mcan0_owner_state.last_protocol_status;
    snapshot->error_count = g_app_mcan0_owner_state.last_error_count;
    snapshot->transmit_error_count =
        MCAN_ECR_TEC_GET(g_app_mcan0_owner_state.last_error_count);
    snapshot->receive_error_count =
        MCAN_ECR_REC_GET(g_app_mcan0_owner_state.last_error_count);
    snapshot->rxfifo0_fill_level =
        g_app_mcan0_owner_state.rxfifo0_fill_level;
    snapshot->rxfifo0_high_watermark =
        g_app_mcan0_owner_state.rxfifo0_high_watermark;
    snapshot->queue_count = g_app_mcan0_owner_state.queue_count;
    snapshot->queue_high_watermark =
        g_app_mcan0_owner_state.queue_high_watermark;
    snapshot->ring_count = g_app_mcan0_owner_state.ring_count;
    snapshot->ring_high_watermark =
        g_app_mcan0_owner_state.ring_high_watermark;
    snapshot->queue_drops = g_app_mcan0_owner_state.queue_drops;
    snapshot->rx_queue_drops =
        g_app_mcan0_owner_state.rx_queue_drops;
    snapshot->diagnostic_queue_drops =
        g_app_mcan0_owner_state.diagnostic_queue_drops;
    snapshot->state_edge_drops =
        g_app_mcan0_owner_state.state_edge_drops;
    snapshot->ring_drops = g_app_mcan0_owner_state.ring_drops;
    snapshot->invalid_frames = g_app_mcan0_owner_state.invalid_frames;
    snapshot->bus_off_count = g_app_mcan0_owner_state.bus_off_count;
    snapshot->warning_count = g_app_mcan0_owner_state.warning_count;
    snapshot->error_passive_count =
        g_app_mcan0_owner_state.error_passive_count;
    snapshot->automatic_recovery_attempts =
        g_app_mcan0_owner_state.automatic_recovery_attempts;
    taskEXIT_CRITICAL();
    return true;
}

app_mcan0_owner_tx_result_t app_mcan0_owner_submit_tx(
    const app_mcan0_owner_tx_request_t *request)
{
    if (request == NULL || request->dlc > APP_MCAN0_OWNER_CLASSIC_MAX_BYTES ||
        request->use_ext_id > 1U || request->rtr > 1U ||
        request->reserved != 0U ||
        (request->use_ext_id == 0U && request->can_id > 0x7FFU) ||
        (request->use_ext_id != 0U && request->can_id > 0x1FFFFFFFU)) {
        g_app_mcan0_owner_state.tx_rejected_invalid++;
        return APP_MCAN0_OWNER_TX_REJECTED_INVALID;
    }
    g_app_mcan0_owner_state.tx_rejected_disarmed++;
    return APP_MCAN0_OWNER_TX_REJECTED_DISARMED;
}
