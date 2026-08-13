from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class BspBannerContractTests(unittest.TestCase):
    def test_root_build_enables_uart_console_and_versions_firmware(self):
        cmake = (ROOT / "CMakeLists.txt").read_text()

        self.assertIn('set(APP_FIRMWARE_VERSION "0.1.0-dev" CACHE STRING', cmake)
        self.assertIn('-DAPP_FIRMWARE_VERSION=\\"${APP_FIRMWARE_VERSION}\\"', cmake)
        self.assertIn('set(APP_BOARD_REVISION "Gerber_PCB1_2026-07-23" CACHE STRING', cmake)
        self.assertIn('-DAPP_BOARD_REVISION=\\"${APP_BOARD_REVISION}\\"', cmake)
        self.assertIn("-DCONFIG_NDEBUG_CONSOLE=0", cmake)
        self.assertNotIn("-DCONFIG_NDEBUG_CONSOLE=1", cmake)
        self.assertNotIn("set(CONFIG_SEGGER_RTT 1)", cmake)
        self.assertIn("sdk_src(${APP_SEGGER_RTT_ROOT}/RTT/SEGGER_RTT.c)", cmake)
        self.assertIn("APP_HPM_SDK_GCC_SOURCES", cmake)
        self.assertIn(
            "${APP_SEGGER_RTT_ROOT}/Syscalls/SEGGER_RTT_Syscalls_GCC.c",
            cmake,
        )
        self.assertIn("list(REMOVE_ITEM APP_HPM_SDK_GCC_SOURCES", cmake)
        self.assertNotIn("-D_write=SEGGER_RTT_unused_write", cmake)
        self.assertIn("APP_HPM_SDK_LINK_LIBRARIES", cmake)
        self.assertIn('"-u _printf_float"', cmake)
        self.assertIn('"-u _scanf_float"', cmake)
        self.assertIn(
            "list(REMOVE_ITEM APP_HPM_SDK_LINK_LIBRARIES",
            cmake,
        )

    def test_board_contract_identifies_uart_and_pcb_revision(self):
        header = (ROOT / "boards/hpm5321_custom/board.h").read_text()
        pinmux = (ROOT / "boards/hpm5321_custom/pinmux.c").read_text()

        self.assertIn("#define BOARD_CONSOLE_UART_BASE HPM_UART0", header)
        self.assertIn("#define BOARD_CONSOLE_UART_BAUDRATE (921600UL)", header)
        self.assertIn("IOC_PA00_FUNC_CTL_UART0_TXD", pinmux)
        self.assertIn("IOC_PA01_FUNC_CTL_UART0_RXD", pinmux)

    def test_banner_reports_versions_board_uart_and_reset_cause(self):
        source = (ROOT / "USER/src/main.c").read_text()

        for token in (
            '"hpm_sdk_version.h"',
            '"P2_BOOT firmware=%s sdk=%s sdk_build=%s board=%s "',
            '"board_revision=%s uart=UART0 baud=%lu reset_flags=0x%08lx "',
            '"reset_cause=%s\\n"',
            "APP_FIRMWARE_VERSION",
            "SDK_VERSION_STRING",
            "APP_SDK_BUILD_VERSION",
            "BOARD_NAME",
            "APP_BOARD_REVISION",
            "BOARD_CONSOLE_UART_BAUDRATE",
        ):
            with self.subTest(token=token):
                self.assertIn(token, source)

        for reset_source in (
            "ppor_reset_brownout",
            "ppor_reset_debug",
            "ppor_reset_wdog0",
            "ppor_reset_wdog1",
            "ppor_reset_pmic_wdog",
            "ppor_reset_software",
        ):
            with self.subTest(reset_source=reset_source):
                self.assertIn(reset_source, source)

        self.assertLess(source.index("capture_clock_state();"),
                        source.index("print_boot_banner();"))
        self.assertLess(source.index("print_boot_banner();"),
                        source.index("vTaskStartScheduler();"))


if __name__ == "__main__":
    unittest.main()
