/*
 * Phase 0 USB High-Speed enumeration probe.
 *
 * This intentionally contains no CAN or product protocol logic. It proves the
 * board USB clock/PHY path, HS negotiation and the mandatory vendor interface.
 */

#include <stdio.h>

#include "board.h"
#include "hpm_usb_drv.h"
#include "usb_config.h"

#define USB_BUS_ID (0U)

extern void winusbv2_init(uint8_t busid, uint32_t reg_base);

int main(void)
{
    board_init();
    board_init_usb((USB_Type *) CONFIG_HPM_USBD_BASE);
    intc_set_irq_priority(CONFIG_HPM_USBD_IRQn, 1);

    printf("HPM5321 Phase0 USB HS vendor-bulk probe\n");
    printf("Expected: USB 2.0 High-Speed, vendor interface 0, WinUSB/libusb\n");

    winusbv2_init(USB_BUS_ID, CONFIG_HPM_USBD_BASE);
    /*
     * usb_dcd_init() resets the PHY, so apply the development-board VBUS
     * override only after CherryUSB initialization, then force a clean
     * disconnect/reconnect for the host to observe the pull-up transition.
     */
    usb_dcd_disconnect((USB_Type *) CONFIG_HPM_USBD_BASE);
    usb_phy_using_internal_vbus((USB_Type *) CONFIG_HPM_USBD_BASE);
    board_delay_ms(100);
    usb_dcd_connect((USB_Type *) CONFIG_HPM_USBD_BASE);

    while (1) {
        ;
    }
}
