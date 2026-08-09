#ifndef APP_IRQ_CONTRACT_H
#define APP_IRQ_CONTRACT_H

#include "FreeRTOSConfig.h"

#if !defined(USE_SYSCALL_INTERRUPT_PRIORITY) ||                          \
    (USE_SYSCALL_INTERRUPT_PRIORITY != 1)
#error "HPM FreeRTOS PLIC threshold support must be enabled"
#endif

#if !defined(configMAX_SYSCALL_INTERRUPT_PRIORITY)
#error "configMAX_SYSCALL_INTERRUPT_PRIORITY must be defined"
#endif

#if configMAX_SYSCALL_INTERRUPT_PRIORITY != 4
#error "P2 IRQ contract requires PLIC syscall threshold 4"
#endif

/* HPM PLIC priority increases with urgency. Priorities above the kernel
 * threshold remain unmasked and therefore cannot call FreeRTOS APIs. */
#define APP_IRQ_FREERTOS_API_PRIORITY_MIN (1U)
#define APP_IRQ_FREERTOS_API_PRIORITY_MAX \
    (configMAX_SYSCALL_INTERRUPT_PRIORITY)
#define APP_IRQ_CAN_CALL_FREERTOS(priority)                              \
    (((priority) >= APP_IRQ_FREERTOS_API_PRIORITY_MIN) &&                \
     ((priority) <= APP_IRQ_FREERTOS_API_PRIORITY_MAX))
#define APP_IRQ_ASSERT_FREERTOS_API_PRIORITY(priority)                   \
    _Static_assert(APP_IRQ_CAN_CALL_FREERTOS(priority),                  \
                   "IRQ using FreeRTOS APIs exceeds the PLIC threshold")

#endif /* APP_IRQ_CONTRACT_H */
