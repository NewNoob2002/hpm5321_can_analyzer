#ifndef CHERRYUSB_CONFIG_H
#define CHERRYUSB_CONFIG_H

#include "board.h"

/* USB callbacks execute in IRQ context; keep that path free of logging. */
#define CONFIG_USB_PRINTF(...) ((void)0)
#define CONFIG_USB_DBG_LEVEL   (-1)

/* Keep dual-speed descriptor handling enabled even in the forced-FS HIL build. */
#define CONFIG_USB_HS
#define CONFIG_USB_ALIGN_SIZE            (4U)
#define USB_NOCACHE_RAM_SECTION          __attribute__((section(".noncacheable.non_init")))

#define USBD_VID                         (0x34B7U)
#define USBD_PID                         (0x1236U)
#define USBD_MAX_POWER                   (200U)

#define CONFIG_USBDEV_REQUEST_BUFFER_LEN (512U)
#define CONFIG_USBDEV_TEST_MODE
#define CONFIG_USBDEV_MAX_BUS USB_SOC_MAX_COUNT

#define CONFIG_HPM_USBD_BASE  HPM_USB0_BASE
#define CONFIG_HPM_USBD_IRQn  IRQn_USB0

#ifndef usb_phyaddr2ramaddr
#define usb_phyaddr2ramaddr(addr) core_local_mem_to_sys_address(BOARD_RUNNING_CORE, (addr))
#endif

#ifndef usb_ramaddr2phyaddr
#define usb_ramaddr2phyaddr(addr) sys_address_to_core_local_mem(BOARD_RUNNING_CORE, (addr))
#endif

#endif /* CHERRYUSB_CONFIG_H */
