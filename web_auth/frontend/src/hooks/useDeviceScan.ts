import { useCallback, useState } from 'react'
import { toast } from 'sonner'
import { device, errorText, type DeviceItem } from '@/lib/api'

/** 设备类型分段控件的三个选项（注册页与验证页共用） */
export const DEVICE_TYPE_OPTIONS = [
  { k: 'all', label: '全部' },
  { k: 'ble', label: '蓝牙' },
  { k: 'serial', label: '串口' },
] as const

export type DeviceType = (typeof DEVICE_TYPE_OPTIONS)[number]['k']

/**
 * 推导设备地址。
 *
 * 三种设备来源字段名不同：BLE 给 `address`、部分安卓库给 `device`、
 * 串口给 `port`。注册页与验证页原先各自写了一遍同样的三元回退。
 */
export function deviceAddress(d: DeviceItem): string {
  return (d.address || d.device || d.port || '') as string
}

/**
 * 设备扫描。
 *
 * 注册页与验证页的扫描逻辑逐字相同（调同一个接口、同样的空列表提示、
 * 同样的 try/catch/finally），差别只在提示文案 —— 那点差别用参数传入，
 * 不必各写一份。
 */
export function useDeviceScan(emptyHint: string) {
  const [deviceType, setDeviceType] = useState<DeviceType>('all')
  const [scanning, setScanning] = useState(false)
  const [devices, setDevices] = useState<DeviceItem[]>([])

  const onScan = useCallback(async () => {
    setScanning(true)
    setDevices([])
    try {
      const res = await device.scan(deviceType)
      if (res.success) {
        const list = res.devices ?? []
        setDevices(list)
        if (list.length === 0) {
          toast.info(emptyHint)
        } else {
          toast.success(`发现 ${list.length} 个设备`)
        }
      } else {
        toast.error(res.error || '扫描失败')
      }
    } catch (err) {
      // 超时（BLE 发现最慢）与后端直接拒绝，提示要能区分
      toast.error(errorText(err, '扫描请求失败'))
    } finally {
      setScanning(false)
    }
  }, [deviceType, emptyHint])

  const reset = useCallback(() => {
    setDevices([])
    setScanning(false)
  }, [])

  return { deviceType, setDeviceType, scanning, devices, onScan, reset }
}
