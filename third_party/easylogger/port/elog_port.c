/*
 * This file is part of the EasyLogger Library.
 *
 * Copyright (c) 2015, Armink, <armink.ztl@gmail.com>
 *
 * Permission is hereby granted, free of charge, to any person obtaining
 * a copy of this software and associated documentation files (the
 * 'Software'), to deal in the Software without restriction, including
 * without limitation the rights to use, copy, modify, merge, publish,
 * distribute, sublicense, and/or sell copies of the Software, and to
 * permit persons to whom the Software is furnished to do so, subject to
 * the following conditions:
 *
 * The above copyright notice and this permission notice shall be
 * included in all copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED 'AS IS', WITHOUT WARRANTY OF ANY KIND,
 * EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
 * MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
 * IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY
 * CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,
 * TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
 * SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
 *
 * Function: Portable interface for each platform.
 * Created on: 2015-04-28
 */

#include <elog.h>
#include "elog_port.h"

#include <stdbool.h>
#include <stdio.h>

#if defined(_WIN32)
#include <windows.h>
static HANDLE s_elog_windows_output_mutex = NULL;
#else
#include "SEGGER_RTT.h"
#endif //_WIN32

static char s_elog_time_buffer[32];

#if defined(ELOG_PORT_USING_THREADX)
#include "tx_api.h"
static TX_MUTEX s_elog_output_mutex;
static volatile bool s_elog_output_mutex_created;
static volatile elog_port_lock_stats_t s_elog_lock_stats;

/**
 * @brief Enter the existing controlled fatal-error path after a logger lock failure.
 *
 * @param None.
 * @retval None. This function does not return.
 *
 * @note The path performs no EasyLogger, UART, allocation, or ThreadX operation,
 *       so it is safe after an invalid ISR entry or mutex ownership failure.
 */
static void elog_port_fail_closed(void) {
    Error_Handler();
    for (;;) {}
}
#elif defined(ELOG_PORT_USING_FREERTOS)

#endif

/**
 * EasyLogger port initialize
 *
 * @return result
 */
ElogErrCode elog_port_init(void) {
#if defined(_WIN32)
    s_elog_windows_output_mutex = CreateMutex(NULL, FALSE, NULL);
#else
    /* add your code here */
    SEGGER_RTT_Init();
#endif //_WIN32
    return ELOG_NO_ERR;
}

/**
 * EasyLogger port deinitialize
 *
 */
void elog_port_deinit(void) {
    /* add your code here */
#if defined(_WIN32)
    CloseHandle(s_elog_windows_output_mutex);
#else
#endif //_WIN32
}

/**
 * output log port interface
 *
 * @param log output of log
 * @param size log size
 */
void elog_port_output(const char* log, const size_t size) {
    /* add your code here */
    SEGGER_RTT_Write(0, log, (unsigned)size);
}

/**
 * @brief Lock EasyLogger's shared formatter and complete output record.
 *
 * @param None.
 * @retval None.
 *
 * @note Allowed only during single-threaded startup or from normal ThreadX
 *       thread context. ISR, fault, and interrupt-masked callers fail closed
 *       without attempting a mutex operation or recursive logging.
 */
void elog_port_output_lock(void) {
#if defined(_WIN32)
    WaitForSingleObject(s_elog_windows_output_mutex, INFINITE);
#elif defined(ELOG_PORT_USING_THREADX)
    TX_THREAD* current_thread;
    UINT status;

    if ((__get_IPSR() != 0U) || (__get_PRIMASK() != 0U) || (__get_FAULTMASK() != 0U)) {
        s_elog_lock_stats.invalid_context_calls++;
        elog_port_fail_closed();
    }

    current_thread = tx_thread_identify();
    if (current_thread == TX_NULL) {
        s_elog_lock_stats.pre_kernel_no_lock_calls++;
        return;
    }
    if (!s_elog_output_mutex_created) {
        s_elog_lock_stats.lock_failures++;
        elog_port_fail_closed();
    }

    status = tx_mutex_get(&s_elog_output_mutex, TX_WAIT_FOREVER);
    if (status != TX_SUCCESS) {
        s_elog_lock_stats.lock_failures++;
        elog_port_fail_closed();
    }
    s_elog_lock_stats.lock_acquisitions++;
#endif //_WIN32
}

/**
 * @brief Unlock EasyLogger's shared formatter and complete output record.
 *
 * @param None.
 * @retval None.
 *
 * @note Startup calls are no-ops until ThreadX has a current thread. ISR,
 *       fault, interrupt-masked, and mutex ownership failures enter the
 *       existing non-recursive controlled fatal-error path.
 */
void elog_port_output_unlock(void) {
#if defined(_WIN32)
    ReleaseMutex(s_elog_windows_output_mutex);
#elif defined(ELOG_PORT_USING_THREADX)
    TX_THREAD* current_thread;
    UINT status;
    UINT previous_posture;

    if ((__get_IPSR() != 0U) || (__get_PRIMASK() != 0U) || (__get_FAULTMASK() != 0U)) {
        s_elog_lock_stats.invalid_context_calls++;
        elog_port_fail_closed();
    }

    current_thread = tx_thread_identify();
    if (current_thread == TX_NULL) {
        s_elog_lock_stats.pre_kernel_no_lock_calls++;
        return;
    }
    if (!s_elog_output_mutex_created) {
        s_elog_lock_stats.unlock_failures++;
        elog_port_fail_closed();
    }

    status = tx_mutex_put(&s_elog_output_mutex);
    if (status != TX_SUCCESS) {
        s_elog_lock_stats.unlock_failures++;
        elog_port_fail_closed();
    }

    previous_posture = tx_interrupt_control(TX_INT_DISABLE);
    s_elog_lock_stats.unlock_operations++;
    (void)tx_interrupt_control(previous_posture);
#endif //_WIN32
}

#if defined(ELOG_PORT_USING_THREADX)
/**
 * @brief Create the Debug EasyLogger output mutex during ThreadX initialization.
 *
 * @param None.
 * @return TX_SUCCESS when the mutex is ready, otherwise a ThreadX status code.
 *
 * @note Call before application thread creation. This function performs no
 *       logging or allocation and is idempotent after successful creation.
 */
UINT elog_port_threadx_init(void) {
    UINT status;

    s_elog_lock_stats.initialization_attempts++;
    if (s_elog_output_mutex_created) {
        return TX_SUCCESS;
    }

    status = tx_mutex_create(&s_elog_output_mutex, (CHAR*)"elog_output", TX_INHERIT);
    if (status == TX_SUCCESS) {
        s_elog_output_mutex_created = true;
        s_elog_lock_stats.mutex_creation_successes++;
    }
    return status;
}

/**
 * @brief Copy a coherent EasyLogger output-lock diagnostic snapshot.
 *
 * @param stats Destination snapshot. Passing NULL leaves state unchanged.
 * @retval None.
 *
 * @note The public ThreadX interrupt-control API protects only bounded raw
 *       counter copying. The prior posture is restored before output update.
 */
void elog_port_get_lock_stats(elog_port_lock_stats_t* stats) {
    elog_port_lock_stats_t raw_stats = {0};
    UINT previous_posture;

    if (stats == NULL) {
        return;
    }
    *stats = (elog_port_lock_stats_t){0};

    previous_posture = tx_interrupt_control(TX_INT_DISABLE);
    raw_stats.initialization_attempts = s_elog_lock_stats.initialization_attempts;
    raw_stats.mutex_creation_successes = s_elog_lock_stats.mutex_creation_successes;
    raw_stats.lock_acquisitions = s_elog_lock_stats.lock_acquisitions;
    raw_stats.unlock_operations = s_elog_lock_stats.unlock_operations;
    raw_stats.lock_failures = s_elog_lock_stats.lock_failures;
    raw_stats.unlock_failures = s_elog_lock_stats.unlock_failures;
    raw_stats.pre_kernel_no_lock_calls = s_elog_lock_stats.pre_kernel_no_lock_calls;
    raw_stats.invalid_context_calls = s_elog_lock_stats.invalid_context_calls;
    raw_stats.mutex_ready = s_elog_output_mutex_created;
    (void)tx_interrupt_control(previous_posture);

    *stats = raw_stats;
}
#endif

/**
 * get current time interface
 *
 * @return current time
 */
const char* elog_port_get_time(void) {
    /* add your code here */
#if defined(_WIN32)
    static char cur_system_time[24] = {0};
    static SYSTEMTIME currTime;

    GetLocalTime(&currTime);
    snprintf(cur_system_time, 24, "%02d-%02d %02d:%02d:%02d.%03d", currTime.wMonth, currTime.wDay, currTime.wHour,
             currTime.wMinute, currTime.wSecond, currTime.wMilliseconds);

    return cur_system_time;
#else
    // snprintf(s_elog_time_buffer, sizeof(s_elog_time_buffer), "%lu", (unsigned long)HAL_GetTick());
    return s_elog_time_buffer;
#endif //_WIN32
}

/**
 * get current process name interface
 *
 * @return current process name
 */
const char* elog_port_get_p_info(void) {
    /* add your code here */
#if defined(_WIN32)
    static char cur_process_info[10] = {0};
    snprintf(cur_process_info, 10, "pid:%04ld", GetCurrentProcessId());

    return cur_process_info;

#else
    return "";
#endif
}

/**
 * get current thread name interface
 *
 * @return current thread name
 */
const char* elog_port_get_t_info(void) {
    /* add your code here */
#if defined(_WIN32)
    static char cur_thread_info[10] = {0};

    snprintf(cur_thread_info, 10, "tid:%04ld", GetCurrentThreadId());

    return cur_thread_info;

#else
    return "";
#endif
}
