#ifndef APP_WATCHDOG_H
#define APP_WATCHDOG_H

#include <stdbool.h>
#include <stdint.h>

#define APP_WATCHDOG_MAGIC (0x57444756U) /* "WDGV" */
#define APP_WATCHDOG_VERSION (1U)
#define APP_WATCHDOG_VOTER_CAPACITY (8U)

typedef enum {
    APP_WATCHDOG_VOTER_HEALTH = 0,
    APP_WATCHDOG_VOTER_TIMER_SERVICE = 1,
} app_watchdog_voter_id_t;

#define APP_WATCHDOG_VOTER_MASK(id) (1UL << (uint32_t)(id))
#define APP_WATCHDOG_REQUIRED_MASK                                           \
    (APP_WATCHDOG_VOTER_MASK(APP_WATCHDOG_VOTER_HEALTH) |                   \
     APP_WATCHDOG_VOTER_MASK(APP_WATCHDOG_VOTER_TIMER_SERVICE))

typedef struct {
    uint32_t magic;
    uint32_t version;
    uint32_t required_mask;
    uint32_t missing_mask;
    uint32_t test_stall_mask;
    uint32_t evaluation_count;
    uint32_t healthy_evaluation_count;
    uint32_t generations[APP_WATCHDOG_VOTER_CAPACITY];
    uint32_t observed_generations[APP_WATCHDOG_VOTER_CAPACITY];
} app_watchdog_state_t;

extern volatile app_watchdog_state_t g_app_watchdog_state;

bool app_watchdog_init(uint32_t required_mask);
void app_watchdog_vote(app_watchdog_voter_id_t voter);
bool app_watchdog_evaluate(void);

#endif /* APP_WATCHDOG_H */
