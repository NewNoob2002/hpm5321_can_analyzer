#ifndef APP_ALLOCATION_H
#define APP_ALLOCATION_H

#include <stdint.h>

#define APP_ALLOCATION_MAGIC (0x414C4C43U) /* "ALLC" */
#define APP_ALLOCATION_VERSION (1U)

typedef struct {
    uint32_t magic;
    uint32_t version;
    uint32_t frozen;
    uint32_t allocation_calls;
    uint32_t free_calls;
    uint32_t allocation_calls_at_freeze;
    uint32_t post_freeze_allocation_calls;
} app_allocation_state_t;

extern volatile app_allocation_state_t g_app_allocation_state;

void app_allocation_freeze(void);

#endif /* APP_ALLOCATION_H */
