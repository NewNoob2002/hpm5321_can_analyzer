#include "app_usb_owner.h"

#include "FreeRTOS.h"
#include "app_irq_contract.h"
#include "app_watchdog.h"
#include "board.h"
#include "hpm_interrupt.h"
#include "hpm_usb_drv.h"
#include "queue.h"
#include "task.h"
#include "usb_config.h"
#include "usbd_core.h"

#define APP_USB_BUS_ID                 (0U)
#define APP_USB_OWNER_STACK_WORDS      (configMINIMAL_STACK_SIZE + 512U)
#define APP_USB_OWNER_QUEUE_LENGTH     (8U)
#define APP_USB_OWNER_TASK_PRIORITY    (3U)
#define APP_USB_OWNER_STARTUP_DELAY_MS (100U)
#define APP_USB_OWNER_POLL_MS          (100U)
#define APP_USB_CONFIG_SIZE            (9U + 9U + 7U + 7U)
#define APP_USB_WINUSB_VENDOR_CODE     (0x17U)

APP_IRQ_ASSERT_FREERTOS_API_PRIORITY(APP_USB_OWNER_ISR_PRIORITY);

typedef enum {
    APP_USB_EVENT_CONFIGURED = 1,
    APP_USB_EVENT_RX_COMPLETE,
    APP_USB_EVENT_TX_COMPLETE,
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

static void process_event(const app_usb_event_t* event) {
    if (event->generation != g_app_usb_owner_state.generation || g_app_usb_owner_state.configured == 0U) {
        g_app_usb_owner_state.stale_events++;
        return;
    }

    switch (event->type) {
        case APP_USB_EVENT_CONFIGURED:
            g_app_usb_owner_state.in_flight = 0U;
            (void)arm_out_transfer();
            break;
        case APP_USB_EVENT_RX_COMPLETE:
            if (event->length > sizeof(usb_transfer_buffer) || g_app_usb_owner_state.in_flight != 0U) {
                g_app_usb_owner_state.transfer_errors++;
                break;
            }
            if (usbd_ep_start_write(APP_USB_BUS_ID, APP_USB_OWNER_IN_EP, usb_transfer_buffer, event->length) != 0) {
                g_app_usb_owner_state.transfer_errors++;
                (void)arm_out_transfer();
                break;
            }
            g_app_usb_owner_state.in_flight = 1U;
            break;
        case APP_USB_EVENT_TX_COMPLETE:
            g_app_usb_owner_state.in_flight = 0U;
            (void)arm_out_transfer();
            break;
        default:
            g_app_usb_owner_state.transfer_errors++;
            break;
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
    vTaskDelay(pdMS_TO_TICKS(APP_USB_OWNER_STARTUP_DELAY_MS));

    intc_m_enable_irq_with_priority(CONFIG_HPM_USBD_IRQn, APP_USB_OWNER_ISR_PRIORITY);
    g_app_usb_owner_state.irq_priority = read_irq_priority(CONFIG_HPM_USBD_IRQn);
    configASSERT(g_app_usb_owner_state.irq_priority == APP_USB_OWNER_ISR_PRIORITY);
    usb_dcd_connect((USB_Type*)CONFIG_HPM_USBD_BASE);
    g_app_usb_owner_state.online = 1U;

    while (1) {
        if (xQueueReceive(usb_owner_queue, &event, pdMS_TO_TICKS(APP_USB_OWNER_POLL_MS)) == pdPASS) {
            process_event(&event);
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
