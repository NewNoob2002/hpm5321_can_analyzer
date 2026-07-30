#pragma once

#include <stdbool.h>
#include <stdint.h>

#if defined(ELOG_PORT_USING_THREADX)
#include "tx_api.h"
#endif

#ifdef __cplusplus
extern "C" {
#endif

/**
 * @brief Snapshot of bounded EasyLogger output-lock diagnostics.
 */
typedef struct {
    uint32_t initialization_attempts;
    uint32_t mutex_creation_successes;
    uint32_t lock_acquisitions;
    uint32_t unlock_operations;
    uint32_t lock_failures;
    uint32_t unlock_failures;
    uint32_t pre_kernel_no_lock_calls;
    uint32_t invalid_context_calls;
    bool mutex_ready;
} elog_port_lock_stats_t;

#if defined(ELOG_PORT_USING_THREADX)
/**
 * @brief Create the Debug EasyLogger output mutex during ThreadX initialization.
 *
 * @param None.
 * @return TX_SUCCESS when the mutex is ready, otherwise a ThreadX status code.
 *
 * @note Call once from tx_application_define() before creating or auto-starting
 *       application threads. The mutex uses priority inheritance and fixed
 *       ThreadX storage; this function never prints or allocates memory.
 */
UINT elog_port_threadx_init(void);

/**
 * @brief Copy a coherent EasyLogger output-lock diagnostic snapshot.
 *
 * @param stats Destination snapshot. Passing NULL leaves state unchanged.
 * @retval None.
 *
 * @note Call from normal ThreadX thread context. The getter briefly uses the
 *       public ThreadX interrupt-control API to copy raw counters, restores the
 *       prior interrupt posture, and never prints, blocks, or allocates memory.
 */
void elog_port_get_lock_stats(elog_port_lock_stats_t* stats);
#endif

#ifdef __cplusplus
}
#endif
