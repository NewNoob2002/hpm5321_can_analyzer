#include "app_usb_owner.h"

#include "FreeRTOS.h"
#include "app_irq_contract.h"
#include "app_mcan0_owner.h"
#include "app_time.h"
#include "app_watchdog.h"
#include "board.h"
#include "hpm_clock_drv.h"
#include "hpm_interrupt.h"
#include "hpm_rng_drv.h"
#include "hpm_usb_drv.h"
#include "queue.h"
#include "task.h"
#include "ucan_codec.h"
#include "ucan_session.h"
#include "usb_config.h"
#include "usbd_core.h"

#include <string.h>

#define APP_USB_BUS_ID                 (0U)
#define APP_USB_OWNER_STACK_WORDS      (configMINIMAL_STACK_SIZE + 512U)
#define APP_USB_OWNER_QUEUE_LENGTH     (8U)
#define APP_USB_OWNER_TASK_PRIORITY    (3U)
#define APP_USB_OWNER_POLL_MS          (100U)
#define APP_USB_CONFIG_SIZE            (9U + 9U + 7U + 7U)
#define APP_USB_WINUSB_VENDOR_CODE     (0x17U)
#define APP_UCAN_MAX_PAYLOAD           (UCAN_QUEUE_FRAME_BYTES - UCAN_HEADER_LEN)
#define APP_UCAN_RX_BATCH_MAX_RECORDS  UCAN_SESSION_MAX_RX_BATCH
#define APP_UCAN_RX_BATCH_WAIT_US      (1000U)
#define APP_UCAN_RX_RECORD_PREFIX_SIZE (20U)
#define APP_UCAN_RX_BATCH_PREFIX_SIZE  (32U)
#define APP_USB_OWNER_IN_AGGREGATE_MAX APP_USB_OWNER_TRANSFER_SIZE

APP_IRQ_ASSERT_FREERTOS_API_PRIORITY(APP_USB_OWNER_ISR_PRIORITY);

typedef enum {
    APP_USB_EVENT_CONFIGURED = 1,
    APP_USB_EVENT_RX_COMPLETE,
    APP_USB_EVENT_TX_COMPLETE,
    APP_USB_EVENT_CAN_RX_READY,
} app_usb_event_type_t;

typedef struct {
    uint32_t type;
    uint32_t generation;
    uint32_t length;
} app_usb_event_t;

static StaticTask_t usb_owner_task_tcb;
static StackType_t usb_owner_task_stack[APP_USB_OWNER_STACK_WORDS];
static StaticQueue_t usb_owner_queue_control;
static uint8_t usb_owner_queue_storage[APP_USB_OWNER_QUEUE_LENGTH * sizeof(app_usb_event_t)];
static QueueHandle_t usb_owner_queue;

USB_NOCACHE_RAM_SECTION USB_MEM_ALIGNX static uint8_t usb_transfer_buffer[APP_USB_OWNER_TRANSFER_SIZE];
USB_NOCACHE_RAM_SECTION USB_MEM_ALIGNX static uint8_t usb_in_buffer[APP_USB_OWNER_TRANSFER_SIZE];
static uint8_t ucan_stream_storage[UCAN_QUEUE_FRAME_BYTES];
static ucan_stream_decoder_t ucan_stream;
static ucan_session_t ucan_session;
static ucan_session_config_t ucan_config;
static ucan_can_rx_record_t mcan_rx_batch_records[APP_UCAN_RX_BATCH_MAX_RECORDS];
static uint8_t mcan_rx_batch_payloads[APP_UCAN_RX_BATCH_MAX_RECORDS]
                                     [APP_MCAN0_OWNER_CLASSIC_MAX_BYTES];
static uint16_t mcan_rx_batch_count;
static uint32_t mcan_rx_batch_record_bytes;
static uint32_t mcan_rx_batch_config_generation;
static uint64_t mcan_rx_batch_base_timestamp;
static uint32_t usb_chunk_length;
static uint32_t usb_chunk_offset;
static uint32_t response_pending;
static uint32_t response_pending_length;
static uint32_t response_pending_frames;
static volatile bool usb_in_zlp_pending;
static volatile bool usb_in_zlp_in_flight;
static uint32_t next_session_id;
static uint64_t boot_epoch;
static uint64_t last_protocol_tick;
static volatile uint32_t protocol_reset_pending;
static bool can_rx_event_pending;
static uint32_t protocol_initialized;
static uint32_t reported_mcan_rx_queue_drops;
static uint32_t reported_mcan_diagnostic_queue_drops;
static uint32_t reported_mcan_state_edge_drops;
static uint32_t reported_mcan_ring_drops;
static uint32_t reported_mcan_state_flags;
static bool mcan_diagnostics_baseline_valid;
static bool mcan_state_reconcile_pending;

volatile app_usb_owner_state_t g_app_usb_owner_state = {
    .magic = APP_USB_OWNER_MAGIC,
    .version = APP_USB_OWNER_VERSION,
};

static const uint8_t ms_os_20_descriptor_set[] = {
    USB_MSOSV2_COMP_ID_SET_HEADER_DESCRIPTOR_INIT(WINUSB_DESCRIPTOR_SET_HEADER_SIZE
                                                  + USB_MSOSV2_COMP_ID_FUNCTION_WINUSB_SINGLE_DESCRIPTOR_LEN),
    USB_MSOSV2_COMP_ID_FUNCTION_WINUSB_SINGLE_DESCRIPTOR_INIT(),
};

static const uint8_t bos_descriptor_data[] = {
    USB_BOS_HEADER_DESCRIPTOR_INIT(5U + USB_BOS_CAP_PLATFORM_WINUSB_DESCRIPTOR_LEN, 1U),
    USB_BOS_CAP_PLATFORM_WINUSB_DESCRIPTOR_INIT(APP_USB_WINUSB_VENDOR_CODE, sizeof(ms_os_20_descriptor_set)),
};

static const struct usb_msosv2_descriptor ms_os_20_descriptor = {
    .vendor_code = APP_USB_WINUSB_VENDOR_CODE,
    .compat_id = ms_os_20_descriptor_set,
    .compat_id_len = sizeof(ms_os_20_descriptor_set),
};

static const struct usb_bos_descriptor bos_descriptor = {
    .string = bos_descriptor_data,
    .string_len = sizeof(bos_descriptor_data),
};

static const uint8_t device_descriptor[] = {
    USB_DEVICE_DESCRIPTOR_INIT(USB_2_1, 0x00, 0x00, 0x00, USBD_VID, USBD_PID, 0x0100, 0x01),
};

static const uint8_t config_descriptor_hs[] = {
    USB_CONFIG_DESCRIPTOR_INIT(APP_USB_CONFIG_SIZE, 0x01, 0x01, USB_CONFIG_BUS_POWERED, USBD_MAX_POWER),
    USB_INTERFACE_DESCRIPTOR_INIT(0x00, 0x00, 0x02, 0xFF, 0xFF, 0x00, 0x04),
    USB_ENDPOINT_DESCRIPTOR_INIT(APP_USB_OWNER_IN_EP, USB_ENDPOINT_TYPE_BULK, USB_BULK_EP_MPS_HS, 0x00),
    USB_ENDPOINT_DESCRIPTOR_INIT(APP_USB_OWNER_OUT_EP, USB_ENDPOINT_TYPE_BULK, USB_BULK_EP_MPS_HS, 0x00),
};

static const uint8_t config_descriptor_fs[] = {
    USB_CONFIG_DESCRIPTOR_INIT(APP_USB_CONFIG_SIZE, 0x01, 0x01, USB_CONFIG_BUS_POWERED, USBD_MAX_POWER),
    USB_INTERFACE_DESCRIPTOR_INIT(0x00, 0x00, 0x02, 0xFF, 0xFF, 0x00, 0x04),
    USB_ENDPOINT_DESCRIPTOR_INIT(APP_USB_OWNER_IN_EP, USB_ENDPOINT_TYPE_BULK, USB_BULK_EP_MPS_FS, 0x00),
    USB_ENDPOINT_DESCRIPTOR_INIT(APP_USB_OWNER_OUT_EP, USB_ENDPOINT_TYPE_BULK, USB_BULK_EP_MPS_FS, 0x00),
};

static const uint8_t device_qualifier_descriptor[] = {
    USB_DEVICE_QUALIFIER_DESCRIPTOR_INIT(USB_2_0, 0x00, 0x00, 0x00, 0x01),
};

static const uint8_t other_speed_descriptor_hs[] = {
    USB_OTHER_SPEED_CONFIG_DESCRIPTOR_INIT(APP_USB_CONFIG_SIZE, 0x01, 0x01, USB_CONFIG_BUS_POWERED, USBD_MAX_POWER),
    USB_INTERFACE_DESCRIPTOR_INIT(0x00, 0x00, 0x02, 0xFF, 0xFF, 0x00, 0x04),
    USB_ENDPOINT_DESCRIPTOR_INIT(APP_USB_OWNER_IN_EP, USB_ENDPOINT_TYPE_BULK, USB_BULK_EP_MPS_FS, 0x00),
    USB_ENDPOINT_DESCRIPTOR_INIT(APP_USB_OWNER_OUT_EP, USB_ENDPOINT_TYPE_BULK, USB_BULK_EP_MPS_FS, 0x00),
};

static const uint8_t other_speed_descriptor_fs[] = {
    USB_OTHER_SPEED_CONFIG_DESCRIPTOR_INIT(APP_USB_CONFIG_SIZE, 0x01, 0x01, USB_CONFIG_BUS_POWERED, USBD_MAX_POWER),
    USB_INTERFACE_DESCRIPTOR_INIT(0x00, 0x00, 0x02, 0xFF, 0xFF, 0x00, 0x04),
    USB_ENDPOINT_DESCRIPTOR_INIT(APP_USB_OWNER_IN_EP, USB_ENDPOINT_TYPE_BULK, USB_BULK_EP_MPS_HS, 0x00),
    USB_ENDPOINT_DESCRIPTOR_INIT(APP_USB_OWNER_OUT_EP, USB_ENDPOINT_TYPE_BULK, USB_BULK_EP_MPS_HS, 0x00),
};

static const char* string_descriptors[] = {
    (const char[]){0x09, 0x04}, "HPMicro", "HPM5321 USB-CAN Analyzer", "HPM5321-P3A-001", "USB-CAN Vendor Bulk",
};

static const uint8_t* device_descriptor_callback(uint8_t speed) {
    (void)speed;
    return device_descriptor;
}

static const uint8_t* config_descriptor_callback(uint8_t speed) {
    if (speed == USB_SPEED_HIGH) {
        return config_descriptor_hs;
    }
    if (speed == USB_SPEED_FULL) {
        return config_descriptor_fs;
    }
    return NULL;
}

static const uint8_t* device_qualifier_descriptor_callback(uint8_t speed) {
    (void)speed;
    return device_qualifier_descriptor;
}

static const uint8_t* other_speed_descriptor_callback(uint8_t speed) {
    if (speed == USB_SPEED_HIGH) {
        return other_speed_descriptor_hs;
    }
    if (speed == USB_SPEED_FULL) {
        return other_speed_descriptor_fs;
    }
    return NULL;
}

static const char* string_descriptor_callback(uint8_t speed, uint8_t index) {
    (void)speed;
    if (index >= (sizeof(string_descriptors) / sizeof(string_descriptors[0]))) {
        return NULL;
    }
    return string_descriptors[index];
}

static const struct usb_descriptor app_usb_descriptor = {
    .device_descriptor_callback = device_descriptor_callback,
    .config_descriptor_callback = config_descriptor_callback,
    .device_quality_descriptor_callback = device_qualifier_descriptor_callback,
    .other_speed_descriptor_callback = other_speed_descriptor_callback,
    .string_descriptor_callback = string_descriptor_callback,
    .msosv2_descriptor = &ms_os_20_descriptor,
    .bos_descriptor = &bos_descriptor,
};

static int get_mcan_diagnostics(void *context,
                                ucan_mcan_diagnostics_t *diagnostics) {
    app_mcan0_diagnostics_t snapshot;
    (void)context;

    if (diagnostics == NULL ||
        !app_mcan0_owner_get_diagnostics(&snapshot)) {
        return -1;
    }
    if (snapshot.snapshot_length != APP_MCAN0_DIAGNOSTICS_SNAPSHOT_LEN) {
        return -1;
    }
    diagnostics->version = snapshot.version;
    diagnostics->length = UCAN_MCAN_DIAGNOSTICS_LEN;
    diagnostics->generation = snapshot.generation;
    diagnostics->state_flags = snapshot.state_flags;
    diagnostics->snapshot_tick = snapshot.snapshot_tick;
    diagnostics->interrupt_flags = snapshot.interrupt_flags;
    diagnostics->error_interrupt_flags = snapshot.error_interrupt_flags;
    diagnostics->last_interrupt_flags = snapshot.last_interrupt_flags;
    diagnostics->protocol_status = snapshot.protocol_status;
    diagnostics->error_count = snapshot.error_count;
    diagnostics->transmit_error_count = snapshot.transmit_error_count;
    diagnostics->receive_error_count = snapshot.receive_error_count;
    diagnostics->rxfifo0_fill_level = snapshot.rxfifo0_fill_level;
    diagnostics->rxfifo0_high_watermark =
        snapshot.rxfifo0_high_watermark;
    diagnostics->queue_count = snapshot.queue_count;
    diagnostics->queue_high_watermark = snapshot.queue_high_watermark;
    diagnostics->ring_count = snapshot.ring_count;
    diagnostics->ring_high_watermark = snapshot.ring_high_watermark;
    diagnostics->queue_drops = snapshot.queue_drops;
    diagnostics->ring_drops = snapshot.ring_drops;
    diagnostics->invalid_frames = snapshot.invalid_frames;
    diagnostics->bus_off_count = snapshot.bus_off_count;
    diagnostics->warning_count = snapshot.warning_count;
    diagnostics->error_passive_count = snapshot.error_passive_count;
    diagnostics->automatic_recovery_attempts =
        snapshot.automatic_recovery_attempts;
    return 0;
}

static void init_protocol_config(void) {
    memset(&ucan_config, 0, sizeof(ucan_config));
    ucan_config.fw_semver = APP_FIRMWARE_VERSION;
    ucan_config.build_id = "hpm5321-product";
    ucan_config.board_id = APP_BOARD_REVISION;
    ucan_config.serial = string_descriptors[3];
    ucan_config.tick_hz = app_time_frequency_hz();
    ucan_config.tick_resolution_ns = (uint32_t)((1000000000ULL + ucan_config.tick_hz - 1U) / ucan_config.tick_hz);
    ucan_config.tx_depth = APP_MCAN0_OWNER_RX_RING_CAPACITY;
    /* The firmware currently owns one reserved synchronous response buffer.
     * Advertise that actual limit instead of the session library's compile-
     * time queue capacity. */
    ucan_config.outstanding_limit = 1U;
    ucan_config.response_capacity = 1U;
    ucan_config.event_capacity = 2U * UCAN_QUEUE_CRITICAL_CAP;
    ucan_config.data_capacity = UCAN_QUEUE_DATA_CAP;
    ucan_config.arm_timeout_min_ms = 100U;
    ucan_config.arm_timeout_max_ms = 60000U;
#ifdef CONFIG_USB_DEVICE_FORCE_FULL_SPEED
    ucan_config.usb_mode = 1U;
#else
    ucan_config.usb_mode = 2U;
#endif
    ucan_config.global_features = 0U;
    ucan_config.replay_cache_entries = UCAN_SESSION_REPLAY_ENTRIES;
    ucan_config.tx_result_cache_entries = UCAN_SESSION_MAX_TX_SLOTS;
    ucan_config.replay_retention_ms = 5000U;
    ucan_config.tag_reuse_guard_ms = 1000U;
    ucan_config.max_message = APP_UCAN_MAX_PAYLOAD;
    ucan_config.channel_count = 1U;
    ucan_config.channels[0].channel = 0U;
    /* The current MCAN owner is intentionally listen-only. Do not advertise
     * Classic/FD TX until that owner implements protocol-controlled modes. */
    ucan_config.channels[0].mode_mask = 0x02U;
    ucan_config.initial_mode[0] = 1U;
    ucan_config.channels[0].feature_bits = 0x0079U;
    ucan_config.channels[0].nominal_min = APP_MCAN0_OWNER_BITRATE;
    ucan_config.channels[0].nominal_max = APP_MCAN0_OWNER_BITRATE;
    ucan_config.channels[0].max_filters = UCAN_SESSION_MAX_FILTERS;
    ucan_config.product_max_bus_load_permille[0] = 0U;
    ucan_config.get_mcan_diagnostics = get_mcan_diagnostics;
}

static void reset_mcan_rx_batch(void) {
    mcan_rx_batch_count = 0U;
    mcan_rx_batch_record_bytes = 0U;
    mcan_rx_batch_config_generation = 0U;
    mcan_rx_batch_base_timestamp = 0U;
}

static void flush_mcan_rx_batch(void) {
    if (mcan_rx_batch_count == 0U) {
        return;
    }
    if (ucan_session_emit_rx_batch_records_at(
            &ucan_session, 0U, mcan_rx_batch_records, mcan_rx_batch_count,
            mcan_rx_batch_base_timestamp) != 0) {
        /* Session admission failures are loss-accounted. Also expose an
         * unexpected builder/session contract violation locally. */
        g_app_usb_owner_state.protocol_dispatch_errors++;
    }
    reset_mcan_rx_batch();
}

static uint32_t mcan_rx_batch_payload_limit(void) {
    uint32_t limit = APP_UCAN_MAX_PAYLOAD;
    if (ucan_session.negotiated &&
        ucan_session.host_rx_max_message != 0U &&
        ucan_session.host_rx_max_message < limit) {
        limit = ucan_session.host_rx_max_message;
    }
    return limit;
}

static bool request_is_mcan_batch_boundary(uint16_t message_type) {
    switch (message_type) {
        case UCAN_MSG_CONFIG_CHANNEL:
        case UCAN_MSG_START_CAPTURE:
        case UCAN_MSG_STOP_CAPTURE:
        case UCAN_MSG_SET_FILTERS:
        case UCAN_MSG_CLEAR_FILTERS:
        case UCAN_MSG_TX_ARM:
        case UCAN_MSG_TX_DISARM:
            return true;
        default:
            return false;
    }
}

static void reset_protocol_session(void) {
    uint64_t usb_rx_bytes = 0U;
    uint64_t usb_tx_bytes = 0U;
    uint32_t diag_generation = 0U;
    ucan_session_channel_t boot_channels[UCAN_SESSION_MAX_CHANNELS];
    memset(boot_channels, 0, sizeof(boot_channels));
    if (protocol_initialized != 0U) {
        usb_rx_bytes = ucan_session.usb_rx_bytes;
        usb_tx_bytes = ucan_session.usb_tx_bytes;
        diag_generation = ucan_session.diag_generation;
        memcpy(boot_channels, ucan_session.channels, sizeof(boot_channels));
    }
    next_session_id++;
    if (next_session_id == 0U) {
        next_session_id = 1U;
    }
    ucan_config.session_id = next_session_id;
    ucan_config.boot_epoch = boot_epoch;
    (void)ucan_session_init(&ucan_session, &ucan_config);
    if (protocol_initialized != 0U) {
        ucan_session.usb_rx_bytes = usb_rx_bytes;
        ucan_session.usb_tx_bytes = usb_tx_bytes;
        ucan_session.diag_generation = diag_generation;
        for (uint8_t i = 0U; i < ucan_config.channel_count; ++i) {
            ucan_session.channels[i].rx_frames = boot_channels[i].rx_frames;
            ucan_session.channels[i].tx_frames = boot_channels[i].tx_frames;
            ucan_session.channels[i].filtered = boot_channels[i].filtered;
            ucan_session.channels[i].dropped = boot_channels[i].dropped;
            ucan_session.channels[i].bus_off_count = boot_channels[i].bus_off_count;
            ucan_session.channels[i].error_count = boot_channels[i].error_count;
        }
    }
    protocol_initialized = 1U;
    (void)ucan_stream_decoder_init(&ucan_stream, ucan_stream_storage, sizeof(ucan_stream_storage),
                                   APP_UCAN_MAX_PAYLOAD);
    ucan_session.tick = app_time_now();
    last_protocol_tick = ucan_session.tick;
    mcan_diagnostics_baseline_valid = false;
    mcan_state_reconcile_pending = false;
    reset_mcan_rx_batch();
    protocol_reset_pending = 0U;
}

static void advance_protocol_clock(void) {
    uint64_t now = app_time_now();
    ucan_session_tick(&ucan_session, now - last_protocol_tick);
    last_protocol_tick = now;
}

static void queue_event(uint32_t type, uint32_t length) {
    const app_usb_event_t event = {
        .type = type,
        .generation = g_app_usb_owner_state.generation,
        .length = length,
    };
    BaseType_t higher_priority_task_woken = pdFALSE;
    BaseType_t result;

    if (xPortIsInsideInterrupt() != pdFALSE) {
        result = xQueueSendFromISR(usb_owner_queue, &event, &higher_priority_task_woken);
        portYIELD_FROM_ISR(higher_priority_task_woken);
    } else {
        result = xQueueSend(usb_owner_queue, &event, 0U);
    }

    if (result == pdPASS) {
        g_app_usb_owner_state.queue_send_count++;
    } else {
        g_app_usb_owner_state.queue_drops++;
    }
}

static void invalidate_session(void) {
    g_app_usb_owner_state.generation++;
    g_app_usb_owner_state.configured = 0U;
    g_app_usb_owner_state.out_armed = 0U;
    g_app_usb_owner_state.in_flight = 0U;
    usb_in_zlp_pending = false;
    usb_in_zlp_in_flight = false;
    protocol_reset_pending = 1U;
}

static void usb_event_handler(uint8_t busid, uint8_t event) {
    (void)busid;

    switch (event) {
        case USBD_EVENT_RESET:
            g_app_usb_owner_state.reset_count++;
            invalidate_session();
            break;
        case USBD_EVENT_CONNECTED:
            g_app_usb_owner_state.connected = 1U;
            g_app_usb_owner_state.connect_count++;
            break;
        case USBD_EVENT_DISCONNECTED:
            g_app_usb_owner_state.connected = 0U;
            g_app_usb_owner_state.disconnect_count++;
            invalidate_session();
            break;
        case USBD_EVENT_CONFIGURED:
            g_app_usb_owner_state.configured = 1U;
            g_app_usb_owner_state.configured_count++;
            queue_event(APP_USB_EVENT_CONFIGURED, 0U);
            break;
        default:
            break;
    }
}

static void usb_out_complete(uint8_t busid, uint8_t ep, uint32_t nbytes) {
    (void)busid;
    (void)ep;
    g_app_usb_owner_state.out_armed = 0U;
    g_app_usb_owner_state.rx_completions++;
    g_app_usb_owner_state.rx_bytes += nbytes;
    queue_event(APP_USB_EVENT_RX_COMPLETE, nbytes);
}

static void usb_in_complete(uint8_t busid, uint8_t ep, uint32_t nbytes) {
    (void)busid;
    (void)ep;
    g_app_usb_owner_state.tx_completions++;
    g_app_usb_owner_state.tx_bytes += nbytes;
    queue_event(APP_USB_EVENT_TX_COMPLETE, nbytes);
}

static struct usbd_endpoint usb_out_endpoint = {
    .ep_addr = APP_USB_OWNER_OUT_EP,
    .ep_cb = usb_out_complete,
};

static struct usbd_endpoint usb_in_endpoint = {
    .ep_addr = APP_USB_OWNER_IN_EP,
    .ep_cb = usb_in_complete,
};

static struct usbd_interface usb_vendor_interface;

static bool arm_out_transfer(void) {
    if (usbd_ep_start_read(APP_USB_BUS_ID, APP_USB_OWNER_OUT_EP, usb_transfer_buffer, sizeof(usb_transfer_buffer))
        != 0) {
        g_app_usb_owner_state.transfer_errors++;
        return false;
    }
    g_app_usb_owner_state.out_armed = 1U;
    return true;
}

static bool start_next_in_transfer(void) {
    if (g_app_usb_owner_state.in_flight != 0U || g_app_usb_owner_state.configured == 0U) {
        return false;
    }
    if (usb_in_zlp_pending) {
        if (usbd_ep_start_write(APP_USB_BUS_ID, APP_USB_OWNER_IN_EP, NULL, 0U)
            != 0) {
            g_app_usb_owner_state.transfer_errors++;
            return false;
        }
        usb_in_zlp_pending = false;
        usb_in_zlp_in_flight = true;
        g_app_usb_owner_state.in_flight = 1U;
        return true;
    }
    uint32_t length = 0U;
    uint32_t event_sequence = 0U;
    if (response_pending != 0U) {
        length = response_pending_length;
    } else {
        if (ucan_session_dequeue(&ucan_session, usb_in_buffer, sizeof(usb_in_buffer), &length, &event_sequence) != 0) {
            return false;
        }
        /* Dequeue is a commit in the session core, so retain the exact bytes
         * locally until the USB controller accepts the transfer. */
        response_pending = 1U;
        response_pending_length = length;
        response_pending_frames = 1U;
        /* Coalesce only complete protocol frames. Since every queued frame is
         * at most UCAN_QUEUE_FRAME_BYTES, checking before dequeue also ensures
         * a dequeued frame can never be stranded. A separate ZLP state machine
         * terminates aggregates whose length is an exact endpoint-MPS
         * multiple. */
        while (APP_USB_OWNER_IN_AGGREGATE_MAX - length >=
               UCAN_QUEUE_FRAME_BYTES) {
            uint32_t next_length = 0U;
            if (ucan_session_dequeue(&ucan_session, usb_in_buffer + length,
                                     APP_USB_OWNER_IN_AGGREGATE_MAX - length,
                                     &next_length,
                                     &event_sequence) != 0) {
                break;
            }
            length += next_length;
            response_pending_length = length;
            response_pending_frames++;
        }
    }
    (void)event_sequence;
    if (usbd_ep_start_write(APP_USB_BUS_ID, APP_USB_OWNER_IN_EP, usb_in_buffer, length) != 0) {
        g_app_usb_owner_state.transfer_errors++;
        return false;
    }
    g_app_usb_owner_state.in_flight = 1U;
    response_pending = 0U;
    response_pending_length = 0U;
    g_app_usb_owner_state.protocol_frames_tx += response_pending_frames;
    response_pending_frames = 0U;
    return true;
}

static void dispatch_usb_chunk(void) {
    while (g_app_usb_owner_state.in_flight == 0U && response_pending == 0U) {
        uint32_t consumed = 0U;
        ucan_frame_t request;
        const uint8_t* input = usb_chunk_offset < usb_chunk_length ? usb_transfer_buffer + usb_chunk_offset : NULL;
        uint32_t input_length = usb_chunk_length - usb_chunk_offset;
        int rc = ucan_stream_decoder_feed(&ucan_stream, input, input_length, &consumed, &request);
        g_app_usb_owner_state.protocol_resync_bytes = (uint32_t)ucan_stream.discarded;
        usb_chunk_offset += consumed;
        if (rc < 0) {
            g_app_usb_owner_state.protocol_dispatch_errors++;
            break;
        }
        if (rc != UCAN_STREAM_FRAME) {
            break;
        }
        g_app_usb_owner_state.protocol_frames_rx++;
        if (request_is_mcan_batch_boundary(request.message_type)) {
            /* Generation/state mutations are ordering boundaries. Read-only
             * requests such as PING and diagnostics must not fragment a live
             * CAN batch or create response-pressure loss. */
            flush_mcan_rx_batch();
        }
        uint32_t response_length = 0U;
        if (ucan_session_handle_frame(&ucan_session, &request, usb_in_buffer, sizeof(usb_in_buffer), &response_length)
                != 0
            || response_length == 0U) {
            g_app_usb_owner_state.protocol_dispatch_errors++;
            continue;
        }
        response_pending = 1U;
        response_pending_length = response_length;
        response_pending_frames = 1U;
        (void)start_next_in_transfer();
    }
}

static uint8_t mcan_channel_state(uint32_t state_flags) {
    if ((state_flags & APP_MCAN0_DIAG_STATE_BUS_OFF) != 0U) {
        return 4U;
    }
    if ((state_flags & APP_MCAN0_DIAG_STATE_ERROR_PASSIVE) != 0U) {
        return 3U;
    }
    if ((state_flags & APP_MCAN0_DIAG_STATE_LISTEN_ONLY) != 0U) {
        return 1U;
    }
    return 0U;
}

static void publish_mcan_diagnostic_edges(void) {
    app_mcan0_diagnostics_t diagnostics;
    app_mcan0_owner_state_edge_t edge;

    if (!app_mcan0_owner_get_diagnostics(&diagnostics)) {
        return;
    }
    if (!mcan_diagnostics_baseline_valid || !ucan_session.negotiated) {
        while (app_mcan0_owner_pop_state_edge(&edge)) {
            /* Establish a fresh post-HELLO baseline without replaying
             * historical controller transitions. */
        }
        reported_mcan_rx_queue_drops = diagnostics.rx_queue_drops;
        reported_mcan_diagnostic_queue_drops =
            diagnostics.diagnostic_queue_drops;
        reported_mcan_state_edge_drops = diagnostics.state_edge_drops;
        reported_mcan_ring_drops = diagnostics.ring_drops;
        reported_mcan_state_flags = diagnostics.state_flags;
        ucan_session.channels[0].state =
            mcan_channel_state(diagnostics.state_flags);
        mcan_diagnostics_baseline_valid = true;
        mcan_state_reconcile_pending = false;
        return;
    }

    while (app_mcan0_owner_pop_state_edge(&edge)) {
        const uint8_t previous_state =
            mcan_channel_state(reported_mcan_state_flags);
        const uint8_t current_state =
            mcan_channel_state(edge.state_flags);
        if (current_state != previous_state) {
            ucan_session_note_channel_state(
                &ucan_session, 0U, current_state, 6U,
                edge.transmit_error_count, edge.receive_error_count,
                edge.timestamp_tick);
        }
        reported_mcan_state_flags = edge.state_flags;
    }

    const uint32_t rx_queue_drops =
        diagnostics.rx_queue_drops - reported_mcan_rx_queue_drops;
    const uint32_t diagnostic_queue_drops =
        diagnostics.diagnostic_queue_drops -
        reported_mcan_diagnostic_queue_drops;
    const uint32_t state_edge_drops =
        diagnostics.state_edge_drops - reported_mcan_state_edge_drops;
    const uint32_t ring_drops =
        diagnostics.ring_drops - reported_mcan_ring_drops;
    if (diagnostic_queue_drops != 0U || state_edge_drops != 0U) {
        /* Diagnostic work loss may have discarded a precise transition.
         * Reconcile only after the owner queue drains, so a delayed exact edge
         * keeps its captured tick. This must not consume channel sequence. */
        mcan_state_reconcile_pending = true;
    }
    ucan_session_note_event_queue_loss(&ucan_session,
                                       diagnostic_queue_drops);
    ucan_session_note_event_queue_loss(&ucan_session, state_edge_drops);
    if (mcan_state_reconcile_pending && diagnostics.queue_count == 0U) {
        const uint8_t previous_state =
            mcan_channel_state(reported_mcan_state_flags);
        const uint8_t current_state =
            mcan_channel_state(diagnostics.state_flags);
        if (current_state != previous_state) {
            ucan_session_note_channel_state(
                &ucan_session, 0U, current_state, 6U,
                diagnostics.transmit_error_count,
                diagnostics.receive_error_count, diagnostics.snapshot_tick);
        }
        reported_mcan_state_flags = diagnostics.state_flags;
        mcan_state_reconcile_pending = false;
    }
    if (rx_queue_drops != 0U) {
        ucan_session_note_rx_ring_loss(&ucan_session, 0U, rx_queue_drops);
    }
    if (ring_drops != 0U) {
        ucan_session_note_rx_ring_loss(&ucan_session, 0U, ring_drops);
    }

    reported_mcan_rx_queue_drops = diagnostics.rx_queue_drops;
    reported_mcan_diagnostic_queue_drops =
        diagnostics.diagnostic_queue_drops;
    reported_mcan_state_edge_drops = diagnostics.state_edge_drops;
    reported_mcan_ring_drops = diagnostics.ring_drops;
}

static void publish_mcan_rx(void) {
    app_mcan0_owner_rx_record_t source;
    while (app_mcan0_owner_pop_rx(&source)) {
        ucan_can_rx_record_t record;
        memset(&record, 0, sizeof(record));
        record.arbitration_id = source.can_id;
        record.channel_sequence = 0U; /* allocated post-filter by session */
        record.flags = (source.use_ext_id ? 0x0001U : 0U) | (source.rtr ? 0x0002U : 0U)
                       | (source.error_state_indicator ? 0x0010U : 0U);
        record.channel = 0U;
        record.dlc = source.dlc;
        record.filter_hit = 0xffU;
        record.payload = source.data;
        record.payload_len = source.rtr ? 0U : source.dlc;
        record.delta_tick = 0U;
        if (ucan_session_on_rx(&ucan_session, 0U, &record) == 0) {
            const uint32_t encoded_bytes =
                APP_UCAN_RX_RECORD_PREFIX_SIZE + record.payload_len;
            const uint32_t payload_limit = mcan_rx_batch_payload_limit();
            const uint64_t previous_timestamp =
                mcan_rx_batch_count == 0U
                    ? source.timestamp_tick
                    : mcan_rx_batch_base_timestamp +
                          mcan_rx_batch_records[mcan_rx_batch_count - 1U]
                              .delta_tick;
            bool flush_before_append =
                mcan_rx_batch_count != 0U &&
                (mcan_rx_batch_config_generation !=
                     ucan_session.config_generation ||
                 source.timestamp_tick < mcan_rx_batch_base_timestamp ||
                 source.timestamp_tick < previous_timestamp ||
                 source.timestamp_tick - mcan_rx_batch_base_timestamp >
                     UINT32_MAX ||
                 mcan_rx_batch_count >= APP_UCAN_RX_BATCH_MAX_RECORDS ||
                 APP_UCAN_RX_BATCH_PREFIX_SIZE +
                         mcan_rx_batch_record_bytes + encoded_bytes >
                     payload_limit);
            if (flush_before_append) {
                flush_mcan_rx_batch();
            }
            if (mcan_rx_batch_count == 0U) {
                mcan_rx_batch_base_timestamp = source.timestamp_tick;
                mcan_rx_batch_config_generation =
                    ucan_session.config_generation;
            }
            const uint16_t index = mcan_rx_batch_count;
            record.delta_tick =
                (uint32_t)(source.timestamp_tick -
                           mcan_rx_batch_base_timestamp);
            if (record.payload_len != 0U) {
                memcpy(mcan_rx_batch_payloads[index], source.data,
                       record.payload_len);
                record.payload = mcan_rx_batch_payloads[index];
            }
            mcan_rx_batch_records[index] = record;
            mcan_rx_batch_count++;
            mcan_rx_batch_record_bytes += encoded_bytes;
            if (mcan_rx_batch_count >= APP_UCAN_RX_BATCH_MAX_RECORDS) {
                flush_mcan_rx_batch();
            }
        }
    }
    if (mcan_rx_batch_count != 0U) {
        const uint64_t wait_ticks =
            ((uint64_t)ucan_config.tick_hz * APP_UCAN_RX_BATCH_WAIT_US +
             999999U) /
            1000000U;
        const uint64_t now = app_time_now();
        if (now >= mcan_rx_batch_base_timestamp &&
            now - mcan_rx_batch_base_timestamp >= wait_ticks) {
            flush_mcan_rx_batch();
        }
    }
}

static void submit_pending_can_tx(void) {
    ucan_can_tx_req_t tx;
    while (ucan_session_take_pending_tx(&ucan_session, &tx) == 0) {
        app_mcan0_owner_tx_request_t request;
        memset(&request, 0, sizeof(request));
        request.can_id = tx.id;
        request.dlc = tx.dlc;
        request.use_ext_id = (tx.can_flags & 0x0001U) != 0U;
        request.rtr = (tx.can_flags & 0x0002U) != 0U;
        if (tx.payload_len > sizeof(request.data)) {
            ucan_session_can_tx_submit_failed(&ucan_session, tx.client_tag, 4U, 0U);
            continue;
        }
        if (tx.payload_len != 0U) {
            memcpy(request.data, tx.payload, tx.payload_len);
        }
        if (app_mcan0_owner_submit_tx(&request) != 0) {
            ucan_session_can_tx_submit_failed(&ucan_session, tx.client_tag, 4U, 0U);
        }
    }
}

static void process_event(const app_usb_event_t* event) {
    if (event->type == APP_USB_EVENT_CAN_RX_READY) {
        /* Wake hint only. The main loop drains the RX level and always closes
         * the producer-latch race after every drain path. */
        return;
    }
    if (event->generation != g_app_usb_owner_state.generation || g_app_usb_owner_state.configured == 0U) {
        g_app_usb_owner_state.stale_events++;
        return;
    }

    switch (event->type) {
        case APP_USB_EVENT_CONFIGURED:
            reset_protocol_session();
            usb_chunk_length = 0U;
            usb_chunk_offset = 0U;
            response_pending = 0U;
            response_pending_length = 0U;
            response_pending_frames = 0U;
            usb_in_zlp_pending = false;
            usb_in_zlp_in_flight = false;
            g_app_usb_owner_state.in_flight = 0U;
            (void)arm_out_transfer();
            break;
        case APP_USB_EVENT_RX_COMPLETE:
            if (event->length > sizeof(usb_transfer_buffer)) {
                g_app_usb_owner_state.transfer_errors++;
                break;
            }
            usb_chunk_length = event->length;
            usb_chunk_offset = 0U;
            dispatch_usb_chunk();
            submit_pending_can_tx();
            if (usb_chunk_offset == usb_chunk_length && g_app_usb_owner_state.in_flight == 0U
                && response_pending == 0U) {
                (void)start_next_in_transfer();
                (void)arm_out_transfer();
            }
            break;
        case APP_USB_EVENT_TX_COMPLETE:
            if (usb_in_zlp_in_flight) {
                usb_in_zlp_in_flight = false;
            } else if (event->length != 0U) {
                const uint16_t endpoint_mps =
                    usbd_get_ep_mps(APP_USB_BUS_ID, APP_USB_OWNER_IN_EP);
                if (endpoint_mps != 0U &&
                    event->length % endpoint_mps == 0U) {
                    usb_in_zlp_pending = true;
                }
            }
            g_app_usb_owner_state.in_flight = 0U;
            dispatch_usb_chunk();
            submit_pending_can_tx();
            if (g_app_usb_owner_state.in_flight == 0U) {
                (void)start_next_in_transfer();
            }
            if (usb_chunk_offset == usb_chunk_length && g_app_usb_owner_state.out_armed == 0U
                && response_pending == 0U) {
                (void)arm_out_transfer();
            }
            break;
        default:
            g_app_usb_owner_state.transfer_errors++;
            break;
    }
}

static void complete_can_rx_drain(void) {
    taskENTER_CRITICAL();
    can_rx_event_pending = false;
    taskEXIT_CRITICAL();

    /* Also covers drains reached through non-CAN wakes or protocol reset. A
     * stale queued CAN_RX_READY is harmless; a stranded level would otherwise
     * wait for the 100 ms idle poll. */
    if (app_mcan0_owner_rx_pending()) {
        (void)app_usb_owner_signal_can_rx();
    }
}

static uint32_t read_irq_priority(uint32_t irq) {
    const uintptr_t address =
        HPM_PLIC_BASE + HPM_PLIC_PRIORITY_OFFSET + ((irq - 1U) << HPM_PLIC_PRIORITY_SHIFT_PER_SOURCE);
    return *(volatile const uint32_t*)address;
}

static void usb_owner_task(void* context) {
    app_usb_event_t event;
    (void)context;

    app_watchdog_vote(APP_WATCHDOG_VOTER_USB_OWNER);

    uint32_t identity[3] = {0U, 0U, 0U};
    clock_add_to_group(clock_rng, 0);
    const bool identity_ready =
        rng_init(HPM_RNG) == status_success && rng_rand_wait(HPM_RNG, identity, sizeof(identity)) == status_success;
    boot_epoch = ((uint64_t)identity[0] << 32) | identity[1];
    /* Protocol identity is a safety boundary. If the hardware RNG cannot
     * provide a nonzero boot/session nonce, fail closed instead of deriving a
     * repeatable identity from fixed startup uptime. */
    configASSERT(identity_ready && boot_epoch != 0U && identity[2] != 0U);
    next_session_id = identity[2];
    init_protocol_config();
    reset_protocol_session();

    intc_m_enable_irq_with_priority(CONFIG_HPM_USBD_IRQn, APP_USB_OWNER_ISR_PRIORITY);
    g_app_usb_owner_state.irq_priority = read_irq_priority(CONFIG_HPM_USBD_IRQn);
    configASSERT(g_app_usb_owner_state.irq_priority == APP_USB_OWNER_ISR_PRIORITY);
    usb_dcd_connect((USB_Type*)CONFIG_HPM_USBD_BASE);
    g_app_usb_owner_state.online = 1U;

    while (1) {
        TickType_t wait_ticks = pdMS_TO_TICKS(APP_USB_OWNER_POLL_MS);
        /* CAN_RX_READY uses a drain/clear/recheck handshake. Poll at 1 ms only
         * while a batch deadline or already-visible ring work is pending. */
        if (mcan_rx_batch_count != 0U || app_mcan0_owner_rx_pending()) {
            wait_ticks = pdMS_TO_TICKS(1U);
            if (wait_ticks == 0U) {
                wait_ticks = 1U;
            }
        }
        if (xQueueReceive(usb_owner_queue, &event, wait_ticks) == pdPASS) {
            /* Timestamp control requests, especially PING, against a protocol
             * clock refreshed after the event arrived but before dispatch.
             * Refreshing only after process_event() makes the reported device
             * tick stale by up to APP_USB_OWNER_POLL_MS while the bus is idle. */
            advance_protocol_clock();
            process_event(&event);
        }
        if (protocol_reset_pending != 0U) {
            reset_protocol_session();
        }
        advance_protocol_clock();
        publish_mcan_rx();
        complete_can_rx_drain();
        publish_mcan_diagnostic_edges();
        ucan_session_poll_flow_control(&ucan_session);
        submit_pending_can_tx();
        if (g_app_usb_owner_state.configured != 0U && g_app_usb_owner_state.in_flight == 0U) {
            (void)start_next_in_transfer();
        }
        app_watchdog_vote(APP_WATCHDOG_VOTER_USB_OWNER);
        g_app_usb_owner_state.stack_high_watermark = uxTaskGetStackHighWaterMark(NULL);
    }
}

/* CherryUSB calls this from usb_dc_init(). Delay the PLIC enable until the
 * scheduler and the statically allocated owner task are running. */
void hpm_usb_isr_enable(uint32_t base) {
    if (base == CONFIG_HPM_USBD_BASE) {
        g_app_usb_owner_state.irq_enable_requests++;
        intc_m_disable_irq(CONFIG_HPM_USBD_IRQn);
    }
}

bool app_usb_owner_start(void) {
    usb_owner_queue = xQueueCreateStatic(APP_USB_OWNER_QUEUE_LENGTH, sizeof(app_usb_event_t), usb_owner_queue_storage,
                                         &usb_owner_queue_control);
    if (usb_owner_queue == NULL) {
        return false;
    }

    if (xTaskCreateStatic(usb_owner_task, "usb_owner", APP_USB_OWNER_STACK_WORDS, NULL, APP_USB_OWNER_TASK_PRIORITY,
                          usb_owner_task_stack, &usb_owner_task_tcb)
        == NULL) {
        return false;
    }

    board_init_usb((USB_Type*)CONFIG_HPM_USBD_BASE);
    usbd_desc_register(APP_USB_BUS_ID, &app_usb_descriptor);
    usbd_add_interface(APP_USB_BUS_ID, &usb_vendor_interface);
    usbd_add_endpoint(APP_USB_BUS_ID, &usb_out_endpoint);
    usbd_add_endpoint(APP_USB_BUS_ID, &usb_in_endpoint);
    if (usbd_initialize(APP_USB_BUS_ID, CONFIG_HPM_USBD_BASE, usb_event_handler) != 0) {
        return false;
    }

    usb_dcd_disconnect((USB_Type*)CONFIG_HPM_USBD_BASE);
    usb_phy_using_internal_vbus((USB_Type*)CONFIG_HPM_USBD_BASE);
    g_app_usb_owner_state.initialized = 1U;
    return true;
}

bool app_usb_owner_signal_can_rx(void) {
    bool should_queue;

    if (usb_owner_queue == NULL) {
        return false;
    }
    taskENTER_CRITICAL();
    should_queue = !can_rx_event_pending;
    can_rx_event_pending = true;
    taskEXIT_CRITICAL();
    if (!should_queue) {
        return true;
    }

    const app_usb_event_t event = {
        .type = APP_USB_EVENT_CAN_RX_READY,
        .generation = g_app_usb_owner_state.generation,
        .length = 0U,
    };
    if (xQueueSend(usb_owner_queue, &event, 0U) == pdPASS) {
        g_app_usb_owner_state.queue_send_count++;
        return true;
    }

    taskENTER_CRITICAL();
    can_rx_event_pending = false;
    taskEXIT_CRITICAL();
    g_app_usb_owner_state.queue_drops++;
    return false;
}
