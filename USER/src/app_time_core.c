#include "app_time_core.h"

#include <stddef.h>

uint64_t app_time_read_stable(app_time_word_reader_t reader,
                              volatile void *context)
{
    uint32_t high_first;
    uint32_t low;
    uint32_t high_second;

    if (reader == NULL) {
        return 0U;
    }

    do {
        high_first = reader(context, 1U);
        low = reader(context, 0U);
        high_second = reader(context, 1U);
    } while (high_first != high_second);

    return ((uint64_t)high_second << 32U) | low;
}
