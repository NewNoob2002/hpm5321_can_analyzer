#include <stdint.h>

#include "FreeRTOS.h"
#include "app_fault.h"
#include "app_time.h"
#include "task.h"

#ifndef APP_FAULT_INJECT_REASON
#define APP_FAULT_INJECT_REASON APP_FAULT_REASON_NONE
#endif

#if APP_FAULT_INJECT_REASON < APP_FAULT_REASON_NONE || \
    APP_FAULT_INJECT_REASON > APP_FAULT_REASON_MALLOC
#error "APP_FAULT_INJECT_REASON must be in the range 0..3"
#endif

volatile app_fault_state_t g_app_fault_state;

static uint32_t hash_string(const char *text)
{
    uint32_t hash = 2166136261U;

    if (text != NULL) {
        while (*text != '\0') {
            hash ^= (uint8_t)*text++;
            hash *= 16777619U;
        }
    }
    return hash;
}

static void app_fatal(uint32_t reason, const char *file, uint32_t line)
{
    taskDISABLE_INTERRUPTS();
    g_app_fault_state.magic = 0U;
    g_app_fault_state.reason = reason;
    g_app_fault_state.line = line;
    g_app_fault_state.file_hash = hash_string(file);
    g_app_fault_state.timestamp = app_time_now();
    g_app_fault_state.magic = APP_FAULT_MAGIC;
    while (1) {
    }
}

void vAssertCalled(const char *file, unsigned long line)
{
    app_fatal(APP_FAULT_ASSERT, file, (uint32_t)line);
}

void vApplicationStackOverflowHook(TaskHandle_t task, char *task_name)
{
    (void)task;
    app_fatal(APP_FAULT_STACK_OVERFLOW, task_name, 0U);
}

void vApplicationMallocFailedHook(void)
{
    app_fatal(APP_FAULT_MALLOC, NULL, 0U);
}

void app_fault_inject_if_configured(void)
{
#if APP_FAULT_INJECT_REASON == APP_FAULT_REASON_ASSERT
    configASSERT(0);
#elif APP_FAULT_INJECT_REASON == APP_FAULT_REASON_STACK_OVERFLOW
    vApplicationStackOverflowHook(NULL, "fault-inject");
#elif APP_FAULT_INJECT_REASON == APP_FAULT_REASON_MALLOC
    vApplicationMallocFailedHook();
#endif
}
