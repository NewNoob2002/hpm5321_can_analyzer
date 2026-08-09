#ifndef APP_FAULT_H
#define APP_FAULT_H

#include <stdint.h>

#define APP_FAULT_MAGIC (0x4641554CU) /* "FAUL" */
#define APP_FAULT_REASON_NONE (0)
#define APP_FAULT_REASON_ASSERT (1)
#define APP_FAULT_REASON_STACK_OVERFLOW (2)
#define APP_FAULT_REASON_MALLOC (3)

typedef enum {
    APP_FAULT_NONE = APP_FAULT_REASON_NONE,
    APP_FAULT_ASSERT = APP_FAULT_REASON_ASSERT,
    APP_FAULT_STACK_OVERFLOW = APP_FAULT_REASON_STACK_OVERFLOW,
    APP_FAULT_MALLOC = APP_FAULT_REASON_MALLOC,
} app_fault_reason_t;

typedef struct {
    uint32_t magic;
    uint32_t reason;
    uint32_t line;
    uint32_t file_hash;
    uint64_t timestamp;
} app_fault_state_t;

extern volatile app_fault_state_t g_app_fault_state;

void app_fault_inject_if_configured(void);

#endif /* APP_FAULT_H */
