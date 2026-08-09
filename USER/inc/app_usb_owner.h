#ifndef APP_USB_OWNER_H
#define APP_USB_OWNER_H

#include <stdbool.h>
#include <stdint.h>

#define APP_USB_OWNER_MAGIC         (0x5553424FU) /* "USBO" */
#define APP_USB_OWNER_VERSION       (1U)
#define APP_USB_OWNER_ISR_PRIORITY  (4U)
#define APP_USB_OWNER_OUT_EP        (0x01U)
#define APP_USB_OWNER_IN_EP         (0x81U)
#define APP_USB_OWNER_TRANSFER_SIZE (2048U)

typedef struct {
    uint32_t magic;
    uint32_t version;
    uint32_t irq_priority;
    uint32_t irq_enable_requests;
    uint32_t initialized;
    uint32_t online;
    uint32_t connected;
    uint32_t configured;
    uint32_t generation;
    uint32_t connect_count;
    uint32_t reset_count;
    uint32_t disconnect_count;
    uint32_t configured_count;
    uint32_t queue_send_count;
    uint32_t queue_drops;
    uint32_t stale_events;
    uint32_t rx_completions;
    uint32_t tx_completions;
    uint64_t rx_bytes;
    uint64_t tx_bytes;
    uint32_t transfer_errors;
    uint32_t out_armed;
    uint32_t in_flight;
    uint32_t stack_high_watermark;
} app_usb_owner_state_t;

extern volatile app_usb_owner_state_t g_app_usb_owner_state;

bool app_usb_owner_start(void);

#endif /* APP_USB_OWNER_H */
