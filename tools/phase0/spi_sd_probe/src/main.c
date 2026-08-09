/* Read-only Phase 0 SPI2 SD/FAT32 characterization probe. */
#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#include "board.h"
#include "diskio.h"
#include "ff.h"
#include "hpm_spi_sdcard.h"
#include "spi_sd_adapt.h"

#define PROBE_MAGIC_RUNNING  (0x50305344U) /* "P0SD" */
#define PROBE_MAGIC_PASS     (0x50415353U) /* "PASS" */
#define PROBE_MAGIC_FAIL     (0x4641494CU) /* "FAIL" */
#define PROBE_MAGIC_NO_MEDIA (0x4E4D4544U) /* "NMED" */
#define PROBE_SPI_INIT_HZ    (400000U)
#define PROBE_SPI_DATA_HZ    (20000000U)

typedef struct {
    uint32_t magic;
    uint32_t version;
    uint32_t card_present;
    int32_t init_status;
    int32_t info_status;
    int32_t sector0_read_status;
    int32_t fatfs_mount_result;
    uint32_t fatfs_type;
    uint32_t card_type;
    uint32_t block_size;
    uint32_t block_count;
    uint32_t capacity_bytes_low;
    uint32_t capacity_bytes_high;
    uint32_t cid_words[4];
    uint32_t csd_device_size;
    uint32_t csd_erase_sector_size;
    uint32_t sector0_checksum;
    uint32_t sector0_signature;
    uint32_t spi_init_hz;
    uint32_t spi_data_hz;
} spi_sd_probe_result_t;

volatile spi_sd_probe_result_t g_spi_sd_probe_result;
ATTR_PLACE_AT_NONCACHEABLE ATTR_ALIGN(HPM_L1C_CACHELINE_SIZE)
uint8_t g_spi_sd_sector0[SPI_SD_BLOCK_SIZE];

static uint32_t fnv1a32(const uint8_t *data, uint32_t size)
{
    uint32_t hash = 2166136261U;
    for (uint32_t i = 0; i < size; ++i) {
        hash ^= data[i];
        hash *= 16777619U;
    }
    return hash;
}

static void finish(uint32_t magic)
{
    g_spi_sd_probe_result.magic = magic;
    while (true) {
        __asm volatile("nop");
    }
}

int main(void)
{
    static FATFS filesystem;
    static const TCHAR drive[] = {DEV_SD + '0', ':', '/', '\0'};
    spi_sdcard_info_t info;

    board_init();
    memset((void *)&g_spi_sd_probe_result, 0, sizeof(g_spi_sd_probe_result));
    memset(&info, 0, sizeof(info));
    memset(g_spi_sd_sector0, 0, sizeof(g_spi_sd_sector0));

    g_spi_sd_probe_result.magic = PROBE_MAGIC_RUNNING;
    g_spi_sd_probe_result.version = 1U;
    g_spi_sd_probe_result.spi_init_hz = PROBE_SPI_INIT_HZ;
    g_spi_sd_probe_result.spi_data_hz = PROBE_SPI_DATA_HZ;
    g_spi_sd_probe_result.card_present = (uint32_t)board_is_sd_card_present();
    if (g_spi_sd_probe_result.card_present == 0U) {
        finish(PROBE_MAGIC_NO_MEDIA);
    }

    g_spi_sd_probe_result.init_status = spi_sd_init();
    if (g_spi_sd_probe_result.init_status != status_success) {
        finish(PROBE_MAGIC_FAIL);
    }

    g_spi_sd_probe_result.info_status = sdcard_spi_get_card_info(&info);
    if (g_spi_sd_probe_result.info_status != status_success) {
        finish(PROBE_MAGIC_FAIL);
    }

    g_spi_sd_probe_result.card_type = info.card_type;
    g_spi_sd_probe_result.block_size = info.block_size;
    g_spi_sd_probe_result.block_count = info.block_count;
    g_spi_sd_probe_result.capacity_bytes_low = (uint32_t)info.capacity;
    g_spi_sd_probe_result.capacity_bytes_high = (uint32_t)(info.capacity >> 32U);
    for (uint32_t i = 0; i < 4U; ++i) {
        g_spi_sd_probe_result.cid_words[i] = info.cid.cid_words[i];
    }
    g_spi_sd_probe_result.csd_device_size = info.csd.device_size;
    g_spi_sd_probe_result.csd_erase_sector_size = info.csd.erase_sector_size;

    g_spi_sd_probe_result.sector0_read_status =
        sdcard_spi_read_block(0U, g_spi_sd_sector0);
    if (g_spi_sd_probe_result.sector0_read_status != status_success) {
        finish(PROBE_MAGIC_FAIL);
    }
    g_spi_sd_probe_result.sector0_checksum =
        fnv1a32(g_spi_sd_sector0, sizeof(g_spi_sd_sector0));
    g_spi_sd_probe_result.sector0_signature =
        (uint32_t)g_spi_sd_sector0[510] |
        ((uint32_t)g_spi_sd_sector0[511] << 8U);

    g_spi_sd_probe_result.fatfs_mount_result = f_mount(&filesystem, drive, 1U);
    g_spi_sd_probe_result.fatfs_type = filesystem.fs_type;
    bool passed =
        (g_spi_sd_probe_result.block_size == SPI_SD_BLOCK_SIZE) &&
        (g_spi_sd_probe_result.block_count > 0U) &&
        (g_spi_sd_probe_result.fatfs_mount_result == FR_OK) &&
        (g_spi_sd_probe_result.fatfs_type == FS_FAT32);
    finish(passed ? PROBE_MAGIC_PASS : PROBE_MAGIC_FAIL);
}
