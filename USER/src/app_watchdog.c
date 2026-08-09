#include "app_watchdog.h"

#include <stddef.h>

volatile app_watchdog_state_t g_app_watchdog_state;

bool app_watchdog_init(uint32_t required_mask)
{
    const uint32_t valid_mask =
        (1UL << APP_WATCHDOG_VOTER_CAPACITY) - 1UL;
    uint32_t index;

    if (required_mask == 0U || (required_mask & ~valid_mask) != 0U) {
        return false;
    }

    g_app_watchdog_state.magic = APP_WATCHDOG_MAGIC;
    g_app_watchdog_state.version = APP_WATCHDOG_VERSION;
    g_app_watchdog_state.required_mask = required_mask;
    g_app_watchdog_state.missing_mask = required_mask;
    g_app_watchdog_state.test_stall_mask = 0U;
    g_app_watchdog_state.evaluation_count = 0U;
    g_app_watchdog_state.healthy_evaluation_count = 0U;
    for (index = 0U; index < APP_WATCHDOG_VOTER_CAPACITY; index++) {
        g_app_watchdog_state.generations[index] = 0U;
        g_app_watchdog_state.observed_generations[index] = 0U;
    }
    return true;
}

void app_watchdog_vote(app_watchdog_voter_id_t voter)
{
    const uint32_t index = (uint32_t)voter;

    if (index >= APP_WATCHDOG_VOTER_CAPACITY) {
        return;
    }

#if defined(DEBUG) || defined(APP_WATCHDOG_TEST)
    if ((g_app_watchdog_state.test_stall_mask &
         APP_WATCHDOG_VOTER_MASK(index)) != 0U) {
        return;
    }
#endif

    g_app_watchdog_state.generations[index]++;
}

bool app_watchdog_evaluate(void)
{
    uint32_t missing_mask = 0U;
    uint32_t index;

    for (index = 0U; index < APP_WATCHDOG_VOTER_CAPACITY; index++) {
        const uint32_t voter_mask = APP_WATCHDOG_VOTER_MASK(index);
        const uint32_t generation =
            g_app_watchdog_state.generations[index];

        if ((g_app_watchdog_state.required_mask & voter_mask) != 0U &&
            generation ==
                g_app_watchdog_state.observed_generations[index]) {
            missing_mask |= voter_mask;
        }
        g_app_watchdog_state.observed_generations[index] = generation;
    }

    g_app_watchdog_state.missing_mask = missing_mask;
    g_app_watchdog_state.evaluation_count++;
    if (missing_mask == 0U) {
        g_app_watchdog_state.healthy_evaluation_count++;
        return true;
    }
    return false;
}
