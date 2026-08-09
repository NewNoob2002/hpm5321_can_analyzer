#ifndef APP_MCAN_IRQ_TEST_H
#define APP_MCAN_IRQ_TEST_H

#include <stdbool.h>
#include <stdint.h>

#define APP_MCAN_IRQ_TEST_MAGIC_RUNNING (0x4D495251U) /* "MIRQ" */
#define APP_MCAN_IRQ_TEST_MAGIC_DONE (0x50415353U)    /* "PASS" */
#define APP_MCAN_IRQ_TEST_MAGIC_FAILED (0x4641494CU)  /* "FAIL" */
#define APP_MCAN_IRQ_TEST_VERSION (1U)
#define APP_MCAN_IRQ_TEST_FRAME_COUNT (1024U)
#define APP_MCAN_IRQ_TEST_ISR_PRIORITY (4U)

typedef struct {
    uint32_t magic;
    uint32_t version;
    int32_t message_ram_status;
    int32_t init_status;
    int32_t last_transmit_status;
    uint32_t irq_priority;
    uint32_t interrupt_count;
    uint32_t interrupt_flags;
    uint32_t error_interrupt_flags;
    uint32_t terminal_fault_flags;
    uint32_t terminal_protocol_status;
    uint32_t terminal_error_count;
    uint32_t tx_error_count;
    uint32_t rx_error_count;
    uint32_t error_logging_count;
    uint32_t frames_submitted;
    uint32_t frames_received;
    uint32_t frames_matched;
    uint32_t frame_mismatches;
    uint32_t queue_send_count;
    uint32_t queue_drops;
    uint32_t receive_timeouts;
    uint32_t receiver_stack_high_watermark;
    int32_t cleanup_status;
    uint32_t post_cleanup_cccr;
    uint32_t cleanup_completed;
} app_mcan_irq_test_state_t;

extern volatile app_mcan_irq_test_state_t g_app_mcan_irq_test_state;

bool app_mcan_irq_test_start(void);

#endif /* APP_MCAN_IRQ_TEST_H */
