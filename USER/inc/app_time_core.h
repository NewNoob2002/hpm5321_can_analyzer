#ifndef APP_TIME_CORE_H
#define APP_TIME_CORE_H

#include <stdint.h>

typedef uint32_t (*app_time_word_reader_t)(volatile void *context,
                                           uint32_t word_index);

uint64_t app_time_read_stable(app_time_word_reader_t reader,
                              volatile void *context);

#endif /* APP_TIME_CORE_H */
