from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class SpiSdProbeContractTests(unittest.TestCase):
    def test_probe_is_read_only_and_checks_detect_geometry_and_fat32(self):
        source = (ROOT / "tools/phase0/spi_sd_probe/src/main.c").read_text()
        self.assertIn("board_is_sd_card_present()", source)
        self.assertIn("sdcard_spi_read_block(0U", source)
        self.assertIn("FS_FAT32", source)
        self.assertIn("info.cid.cid_words", source)
        self.assertNotIn("sdcard_spi_write", source)
        self.assertNotIn("f_write", source)

    def test_probe_uses_repo_adapter_and_20_mhz_ceiling(self):
        cmake = (ROOT / "tools/phase0/spi_sd_probe/CMakeLists.txt").read_text()
        self.assertIn("sdk_app_src(src/spi_sd_adapt.c)", cmake)
        self.assertNotIn("samples/spi_sdcard/common/adapt/spi_sd_adapt.c", cmake)
        self.assertIn("SPI_SD_SPEED_MAX_HZ=20000000", cmake)
        self.assertIn("USE_DMA_TRANSFER=0", cmake)
        self.assertIn("set(CONFIG_DMA_MGR 1)", cmake)

    def test_repo_adapter_uses_mode0_real_detect_and_finite_transfers(self):
        source = (
            ROOT / "tools/phase0/spi_sd_probe/src/spi_sd_adapt.c"
        ).read_text()
        self.assertIn("spi_sclk_low_idle", source)
        self.assertIn("spi_sclk_sampling_odd_clk_edges", source)
        self.assertIn("return board_is_sd_card_present();", source)
        self.assertIn("SD_SPI_TRANSFER_TIMEOUT_MS (1000U)", source)
        self.assertIn('#include <stdio.h>', source)
        self.assertNotIn("0xFFFFFFFF", source)
        self.assertNotIn("return true;", source)
        self.assertIn("g_spi_sd_bus_diagnostics.last_command", source)
        self.assertIn("g_spi_sd_bus_diagnostics.last_non_ff_rx", source)
        self.assertIn("SD_SPI_CMD8_SDK_CRC (0x86U)", source)
        self.assertIn("SD_SPI_CMD8_WIRE_CRC (0x87U)", source)

    def test_board_detect_input_has_explicit_pull_up_and_hysteresis(self):
        pinmux = (ROOT / "boards/hpm5321_custom/pinmux.c").read_text()
        self.assertIn("IOC_PAD_PAD_CTL_HYS_SET(1)", pinmux)
        self.assertIn("IOC_PAD_PAD_CTL_PE_SET(1)", pinmux)
        self.assertIn("IOC_PAD_PAD_CTL_PS_SET(1)", pinmux)
        self.assertIn("IOC_PAD_PAD_CTL_PRS_SET(0)", pinmux)
        self.assertIn(
            "HPM_PIOC->PAD[IOC_PAD_PY00].PAD_CTL = BOARD_SD_DETECT_PAD_CTL;",
            pinmux,
        )
        self.assertIn(
            "HPM_IOC->PAD[IOC_PAD_PB12].PAD_CTL = BOARD_SPI_MISO_PAD_CTL;",
            pinmux,
        )


if __name__ == "__main__":
    unittest.main()
