/* Phase 0 five-LED pin, polarity, and routing probe. */
#include <stdint.h>
#include <stdio.h>

#include "board.h"
#include "hpm_gpio_drv.h"

#if LED_CHASER_STEP_MS < 1
#error "LED_CHASER_STEP_MS must be at least 1 ms"
#endif

#define LED_CHASER_MAGIC (0x4C454453U) /* "LEDS" */
#define LED_COUNT (5U)

typedef struct {
    GPIO_Type *gpio;
    uint32_t port;
    uint8_t pin;
    uint8_t on_level;
    uint8_t off_level;
    const char *name;
} led_pin_t;

typedef struct {
    uint32_t magic;
    uint32_t version;
    uint32_t current_index;
    uint32_t completed_cycles;
    uint32_t step_ms;
} led_chaser_state_t;

static const led_pin_t led_sequence[LED_COUNT] = {
    {BOARD_LED_GPIO_CTRL, BOARD_LED_GPIO_INDEX, BOARD_LED_GPIO_PIN,
     BOARD_LED_ON_LEVEL, BOARD_LED_OFF_LEVEL, "STATUS/PA31"},
    {BOARD_CAN0_TX_LED_GPIO_CTRL, BOARD_CAN0_TX_LED_GPIO_INDEX,
     BOARD_CAN0_TX_LED_GPIO_PIN, BOARD_CAN_LED_ON_LEVEL,
     BOARD_CAN_LED_OFF_LEVEL, "CAN1_TX/PY01"},
    {BOARD_CAN0_RX_LED_GPIO_CTRL, BOARD_CAN0_RX_LED_GPIO_INDEX,
     BOARD_CAN0_RX_LED_GPIO_PIN, BOARD_CAN_LED_ON_LEVEL,
     BOARD_CAN_LED_OFF_LEVEL, "CAN1_RX/PY02"},
    {BOARD_CAN2_TX_LED_GPIO_CTRL, BOARD_CAN2_TX_LED_GPIO_INDEX,
     BOARD_CAN2_TX_LED_GPIO_PIN, BOARD_CAN_LED_ON_LEVEL,
     BOARD_CAN_LED_OFF_LEVEL, "CAN2_TX/PY03"},
    {BOARD_CAN2_RX_LED_GPIO_CTRL, BOARD_CAN2_RX_LED_GPIO_INDEX,
     BOARD_CAN2_RX_LED_GPIO_PIN, BOARD_CAN_LED_ON_LEVEL,
     BOARD_CAN_LED_OFF_LEVEL, "CAN2_RX/PA09"},
};

volatile led_chaser_state_t g_led_chaser_state = {
    .magic = LED_CHASER_MAGIC,
    .version = 1U,
    .current_index = LED_COUNT,
    .completed_cycles = 0U,
    .step_ms = LED_CHASER_STEP_MS,
};

static void write_led(const led_pin_t *led, uint8_t level)
{
    gpio_write_pin(led->gpio, led->port, led->pin, level);
}

static void turn_all_leds_off(void)
{
    for (uint32_t i = 0U; i < LED_COUNT; ++i) {
        write_led(&led_sequence[i], led_sequence[i].off_level);
    }
    g_led_chaser_state.current_index = LED_COUNT;
}

int main(void)
{
    board_init();
    turn_all_leds_off();

    printf("HPM5321 five-LED chaser: %u ms per step\n",
           (unsigned int)LED_CHASER_STEP_MS);
    for (uint32_t i = 0U; i < LED_COUNT; ++i) {
        printf("  %u: %s\n", (unsigned int)i, led_sequence[i].name);
    }

    board_delay_ms(LED_CHASER_STEP_MS);
    while (1) {
        for (uint32_t i = 0U; i < LED_COUNT; ++i) {
            turn_all_leds_off();
            write_led(&led_sequence[i], led_sequence[i].on_level);
            g_led_chaser_state.current_index = i;
            board_delay_ms(LED_CHASER_STEP_MS);
        }
        g_led_chaser_state.completed_cycles++;
    }
}
