#include "app_time.h"

#include <stdint.h>

#include "app_time_core.h"
#include "hpm_clock_drv.h"
#include "hpm_soc.h"

static uint32_t read_mchtmr_word(volatile void *context, uint32_t word_index)
{
    volatile uint32_t *mtime = (volatile uint32_t *)context;

    return mtime[word_index];
}

uint64_t app_time_now(void)
{
    volatile uint32_t *mtime =
        (volatile uint32_t *)(uintptr_t)HPM_MCHTMR_BASE;

    return app_time_read_stable(read_mchtmr_word, mtime);
}

uint32_t app_time_frequency_hz(void)
{
    return clock_get_frequency(clock_mchtmr0);
}
