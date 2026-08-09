#include "app_allocation.h"

#include <stddef.h>
#include <stdlib.h>

struct _reent;

void *__real_malloc(size_t size);
void *__real_calloc(size_t count, size_t size);
void *__real_realloc(void *memory, size_t size);
void __real_free(void *memory);
void *__real__malloc_r(struct _reent *reent, size_t size);
void *__real__calloc_r(struct _reent *reent, size_t count, size_t size);
void *__real__realloc_r(struct _reent *reent, void *memory, size_t size);
void __real__free_r(struct _reent *reent, void *memory);

volatile app_allocation_state_t g_app_allocation_state = {
    .magic = APP_ALLOCATION_MAGIC,
    .version = APP_ALLOCATION_VERSION,
};

static void record_allocation(void)
{
    g_app_allocation_state.allocation_calls++;
    if (g_app_allocation_state.frozen != 0U) {
        g_app_allocation_state.post_freeze_allocation_calls++;
    }
}

static void record_free(void)
{
    g_app_allocation_state.free_calls++;
}

void app_allocation_freeze(void)
{
    g_app_allocation_state.allocation_calls_at_freeze =
        g_app_allocation_state.allocation_calls;
    g_app_allocation_state.post_freeze_allocation_calls = 0U;
    g_app_allocation_state.frozen = 1U;
}

void *__wrap_malloc(size_t size)
{
    record_allocation();
    return __real_malloc(size);
}

void *__wrap_calloc(size_t count, size_t size)
{
    record_allocation();
    return __real_calloc(count, size);
}

void *__wrap_realloc(void *memory, size_t size)
{
    record_allocation();
    return __real_realloc(memory, size);
}

void __wrap_free(void *memory)
{
    record_free();
    __real_free(memory);
}

void *__wrap__malloc_r(struct _reent *reent, size_t size)
{
    record_allocation();
    return __real__malloc_r(reent, size);
}

void *__wrap__calloc_r(struct _reent *reent, size_t count, size_t size)
{
    record_allocation();
    return __real__calloc_r(reent, count, size);
}

void *__wrap__realloc_r(struct _reent *reent, void *memory, size_t size)
{
    record_allocation();
    return __real__realloc_r(reent, memory, size);
}

void __wrap__free_r(struct _reent *reent, void *memory)
{
    record_free();
    __real__free_r(reent, memory);
}
