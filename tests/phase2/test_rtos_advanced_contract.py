from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[2]
USER = ROOT / "USER"


def compile_and_run(harness: str, sources: list[Path], defines=()):
    with tempfile.TemporaryDirectory() as temporary_directory:
        executable = Path(temporary_directory) / "contract_test"
        command = [
            "cc",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            f"-I{USER / 'inc'}",
            *[f"-D{define}" for define in defines],
            "-x",
            "c",
            "-",
            *map(str, sources),
            "-o",
            str(executable),
        ]
        subprocess.run(
            command,
            cwd=ROOT,
            input=harness,
            text=True,
            check=True,
            capture_output=True,
        )
        subprocess.run([str(executable)], check=True, capture_output=True)


class RtosAdvancedContractTests(unittest.TestCase):
    def test_time_core_retries_stable_rollover_and_torn_reads(self):
        harness = textwrap.dedent(
            r"""
            #include <assert.h>
            #include <stddef.h>
            #include <stdint.h>
            #include "app_time_core.h"

            typedef struct {
                const uint32_t *values;
                size_t length;
                size_t position;
            } sequence_t;

            static uint32_t read_sequence(volatile void *context,
                                          uint32_t word_index)
            {
                sequence_t *sequence = (sequence_t *)context;
                static const uint32_t expected_indices[] = {1U, 0U, 1U};
                assert(sequence->position < sequence->length);
                assert(word_index == expected_indices[sequence->position % 3U]);
                return sequence->values[sequence->position++];
            }

            static void verify(const uint32_t *values, size_t length,
                               uint64_t expected)
            {
                sequence_t sequence = {values, length, 0U};
                assert(app_time_read_stable(read_sequence, &sequence) == expected);
                assert(sequence.position == length);
            }

            int main(void)
            {
                const uint32_t stable[] = {1U, 0x89abcdefU, 1U};
                const uint32_t rollover[] = {
                    1U, 0xffffffffU, 2U,
                    2U, 0U, 2U,
                };
                const uint32_t torn_twice[] = {
                    7U, 0xffffffffU, 8U,
                    8U, 0xffffffffU, 9U,
                    9U, 1U, 9U,
                };

                verify(stable, 3U, UINT64_C(0x0000000189abcdef));
                verify(rollover, 6U, UINT64_C(0x0000000200000000));
                verify(torn_twice, 9U, UINT64_C(0x0000000900000001));
                assert(app_time_read_stable(NULL, NULL) == 0U);
                return 0;
            }
            """
        )
        compile_and_run(harness, [USER / "src/app_time_core.c"])

    def test_watchdog_reports_each_missing_generation(self):
        harness = textwrap.dedent(
            r"""
            #include <assert.h>
            #include <stdint.h>
            #include "app_watchdog.h"

            int main(void)
            {
                const uint32_t health =
                    APP_WATCHDOG_VOTER_MASK(APP_WATCHDOG_VOTER_HEALTH);
                const uint32_t timer =
                    APP_WATCHDOG_VOTER_MASK(APP_WATCHDOG_VOTER_TIMER_SERVICE);
                const uint32_t usb =
                    APP_WATCHDOG_VOTER_MASK(APP_WATCHDOG_VOTER_USB_OWNER);

                assert(!app_watchdog_init(0U));
                assert(!app_watchdog_init(1UL << APP_WATCHDOG_VOTER_CAPACITY));
                assert(app_watchdog_init(APP_WATCHDOG_REQUIRED_MASK));
                assert(!app_watchdog_evaluate());
                assert(g_app_watchdog_state.missing_mask ==
                       (health | timer | usb));

                app_watchdog_vote(APP_WATCHDOG_VOTER_HEALTH);
                app_watchdog_vote(APP_WATCHDOG_VOTER_TIMER_SERVICE);
                app_watchdog_vote(APP_WATCHDOG_VOTER_USB_OWNER);
                assert(app_watchdog_evaluate());
                assert(g_app_watchdog_state.missing_mask == 0U);

                g_app_watchdog_state.test_stall_mask = timer;
                app_watchdog_vote(APP_WATCHDOG_VOTER_HEALTH);
                app_watchdog_vote(APP_WATCHDOG_VOTER_TIMER_SERVICE);
                app_watchdog_vote(APP_WATCHDOG_VOTER_USB_OWNER);
                assert(!app_watchdog_evaluate());
                assert(g_app_watchdog_state.missing_mask == timer);

                g_app_watchdog_state.test_stall_mask = health;
                app_watchdog_vote(APP_WATCHDOG_VOTER_HEALTH);
                app_watchdog_vote(APP_WATCHDOG_VOTER_TIMER_SERVICE);
                app_watchdog_vote(APP_WATCHDOG_VOTER_USB_OWNER);
                assert(!app_watchdog_evaluate());
                assert(g_app_watchdog_state.missing_mask == health);

                g_app_watchdog_state.test_stall_mask = 0U;
                app_watchdog_vote(APP_WATCHDOG_VOTER_HEALTH);
                app_watchdog_vote(APP_WATCHDOG_VOTER_TIMER_SERVICE);
                app_watchdog_vote(APP_WATCHDOG_VOTER_USB_OWNER);
                assert(app_watchdog_evaluate());
                assert(g_app_watchdog_state.healthy_evaluation_count == 2U);
                assert(g_app_watchdog_state.evaluation_count == 5U);
                return 0;
            }
            """
        )
        compile_and_run(
            harness,
            [USER / "src/app_watchdog.c"],
            defines=("APP_WATCHDOG_TEST=1",),
        )

    def test_irq_and_fault_injection_contracts_are_frozen(self):
        cmake = (ROOT / "CMakeLists.txt").read_text()
        irq = (USER / "inc/app_irq_contract.h").read_text()
        hooks = (USER / "src/freertos_hooks.c").read_text()
        main = (USER / "src/main.c").read_text()

        self.assertIn("-DUSE_SYSCALL_INTERRUPT_PRIORITY=1", cmake)
        self.assertIn("APP_IRQ_FREERTOS_API_PRIORITY_MAX", irq)
        self.assertIn("APP_IRQ_ASSERT_FREERTOS_API_PRIORITY", irq)
        self.assertIn("APP_FAULT_INJECT_REASON", cmake)
        self.assertIn("app_fault_inject_if_configured();", main)
        self.assertNotIn("ebreak", hooks)

    def test_mcan0_irq_qualification_uses_static_freertos_path(self):
        cmake = (ROOT / "CMakeLists.txt").read_text()
        source = (USER / "src/app_mcan_irq_test.c").read_text()
        header = (USER / "inc/app_mcan_irq_test.h").read_text()
        main = (USER / "src/main.c").read_text()

        self.assertIn("sdk_app_src(USER/src/app_mcan_irq_test.c)", cmake)
        self.assertIn("APP_MCAN_IRQ_TEST_ISR_PRIORITY (4U)", header)
        self.assertIn(
            "APP_IRQ_ASSERT_FREERTOS_API_PRIORITY(APP_MCAN_IRQ_TEST_ISR_PRIORITY)",
            source,
        )
        self.assertIn("mcan_mode_loopback_internal", source)
        self.assertIn("SDK_DECLARE_EXT_ISR_M(BOARD_CAN0_IRQn", source)
        self.assertIn("xQueueSendFromISR", source)
        self.assertIn("xQueueCreateStatic", source)
        self.assertIn("xTaskCreateStatic", source)
        self.assertIn("intc_m_enable_irq_with_priority", source)
        self.assertIn("mcan_begin_reconfig", source)
        self.assertIn("cleanup_completed", source)
        self.assertIn("terminal_fault_flags", header)
        self.assertNotIn("board_init_can(HPM_MCAN0)", source)
        self.assertNotIn("xQueueCreate(", source)
        self.assertNotIn("xTaskCreate(", source)
        self.assertLess(
            main.index("app_mcan_irq_test_start()"),
            main.index("app_allocation_freeze();"),
        )
        self.assertIn("app_usb_owner_start()", main)
        self.assertNotIn("mcan_owner_task", main)

    def test_frozen_heartbeat_runner_pins_the_qualified_elf(self):
        runner = (ROOT / "scripts/phase2/run_frozen_heartbeat.sh").read_text()

        self.assertIn(
            'FROZEN_ELF_SHA256="c3feef5d36867d021e26a95548b4bd055150ca2e4be54cf907d847c8afee70d2"',
            runner,
        )
        self.assertIn('--expected-elf-sha256 "${FROZEN_ELF_SHA256}"', runner)
        self.assertIn('P2_FROZEN_ELF=', runner)
        self.assertIn('--elf "${P2_FROZEN_ELF}"', runner)
        self.assertIn('DURATION_SECONDS="${1:-86400}"', runner)
        self.assertIn('--interval-seconds "${INTERVAL_SECONDS:-60}"', runner)
        self.assertIn('GNURISCV_TOOLCHAIN_PATH', runner)
        self.assertIn('command -v JLinkGDBServerCLExe', runner)
        self.assertIn('--gdb "${GDB}"', runner)
        self.assertIn('--gdb-server "${GDB_SERVER}"', runner)

    def test_timer_votes_and_health_independently_evaluates(self):
        source = (USER / "src/app_health.c").read_text()

        self.assertIn(
            "app_watchdog_vote(APP_WATCHDOG_VOTER_TIMER_SERVICE)", source
        )
        self.assertIn(
            "app_watchdog_vote(APP_WATCHDOG_VOTER_HEALTH)", source
        )
        self.assertIn("app_watchdog_evaluate()", source)
        self.assertIn("pdMS_TO_TICKS(APP_HEALTH_HEARTBEAT_MS)", source)
        self.assertNotIn("portMAX_DELAY", source)

    def test_boot_state_captures_reset_source(self):
        source = (USER / "src/main.c").read_text()

        self.assertIn("ppor_reset_get_flags(HPM_PPOR)", source)
        self.assertIn("g_app_boot_state.reset_flags = reset_flags", source)
        self.assertIn("g_app_boot_state.boot_timestamp = app_time_now()", source)
        self.assertIn("ppor_reset_clear_flags(HPM_PPOR, reset_flags)", source)

    def test_runtime_allocation_is_counted_and_frozen_before_scheduler(self):
        cmake = (ROOT / "CMakeLists.txt").read_text()
        allocation = (USER / "src/app_allocation.c").read_text()
        main = (USER / "src/main.c").read_text()

        for symbol in ("malloc", "calloc", "realloc", "free"):
            self.assertIn(f"__wrap_{symbol}", allocation)
        self.assertIn("--wrap=${allocation_symbol}", cmake)
        self.assertLess(
            main.index("app_allocation_freeze();"),
            main.index("vTaskStartScheduler();"),
        )


if __name__ == "__main__":
    unittest.main()
