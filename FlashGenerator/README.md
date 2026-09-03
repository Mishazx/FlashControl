# FlashGenerator

Генератор synthetic USB-носителей и test suite для **FlashControl probe** в Proxmox/QEMU + Windows 11.

Образы подключаются к VM **как USB Mass Storage**, не как VirtIO/SCSI диск.

## Структура

```text
FlashGenerator/
  generate.py           # генерация raw .img
  attach.sh / detach.sh # hot-plug в VM 5000
  run_vm_suite.sh       # прогон suite на Proxmox
  run_probe_tests.ps1   # сбор JSON в Windows VM
  analyze_results.py    # проверка результатов
  test_suite.json       # список профилей и comparisons
  qemu_attach.py       # сборка QEMU usb-storage identity
  profiles/             # 15 JSON-профилей
  output/               # образы (gitignored)
  results/              # JSON от probe (gitignored)
```

## Зависимости

**Proxmox host:**

```bash
apt install qemu-utils gdisk parted dosfstools ntfs-3g exfatprogs python3
chmod +x generate.py attach.sh detach.sh run_vm_suite.sh analyze_results.py qemu_attach.py
```

**Windows 11 VM:** Python 3 + FlashControlAgent.

## Профили (15)

| Профиль | Назначение |
|---------|------------|
| `baseline_mbr_fat32` | MBR + FAT32 smoke |
| `gpt_single_ntfs` | GPT + NTFS + GUID |
| `dual_partition_mbr` | MBR, FAT32 + exFAT |
| `gpt_dual_partition` | GPT, FAT32 + NTFS |
| `exfat_single` | GPT + exFAT |
| `mbr_boot_flag` | MBR bootable partition |
| `empty_raw` | Raw без таблицы разделов |
| `gpt_unformatted` | GPT без отформатированных томов |
| `large_4g` | ~4 GiB geometry |
| `collision_media_a/b` | Разный media, **одинаковый** `qemu_attach` |
| `hardware_variant_a/b` | Одинаковый media, **разный** `qemu_attach` |
| `rename_test_base` | Ручной rename-тест |
| `format_test_base` | Ручной format-тест |

## Опциональная hardware-identity (QEMU)

FlashGenerator задаёт media в `.img`. Hardware probe читает из эмуляции USB.

В профиле (и manifest `output/*.img.json`):

```json
"qemu_attach": {
  "usb_serial": "FG-COLL-SHARED",
  "drive_serial": "STOR-COLLIDE",
  "vendor_id": "0781",
  "product_id": "5583",
  "removable": true
}
```

| Поле | Куда попадает в probe | Надёжность в QEMU |
|------|------------------------|-------------------|
| `usb_serial` | PnP USB serial candidate | Обычно работает |
| `drive_serial` | Storage descriptor serial | Обычно работает (`drive_add serial=`) |
| `vendor_id` / `product_id` | VID/PID | Best-effort, зависит от версии QEMU |
| `removable` | removable media flag | Обычно работает |

Переопределение без правки профиля:

```bash
QEMU_USB_SERIAL=FG-OVERRIDE-99 \
QEMU_DRIVE_SERIAL=STOR-OVERRIDE-99 \
sudo ./attach.sh output/baseline_mbr_fat32.img
```

После `generate --force` manifest содержит `qemu_attach` — `attach.sh` подхватывает автоматически.

**Comparisons в suite:**

- `collision_media_a/b` — same hardware (shared `qemu_attach`), different media
- `hardware_variant_a/b` — same media layout, different `qemu_attach`

Перегенерируй образы после смены `qemu_attach` в профилях (manifest пишется при generate).

## Быстрый старт

### 1. Proxmox — сгенерировать образы

```bash
cd /path/to/FlashControl/FlashGenerator
sudo ./run_vm_suite.sh generate --force
```

### 2. Windows VM — watcher (терминал 1)

```powershell
cd C:\path\to\FlashControl\FlashGenerator
.\run_probe_tests.ps1 -Watch -ShareDir Z:\flashcontrol
```

Опционально: shared folder `Z:\flashcontrol` ↔ `/mnt/flashcontrol` на хосте, тогда:

```bash
export FLASHGEN_SHARE=/mnt/flashcontrol
```

### 3. Proxmox — прогон suite (терминал 2)

```bash
qm start 5000
sudo FLASHGEN_SHARE=/mnt/flashcontrol DELAY=25 ./run_vm_suite.sh suite
```

Suite attach/detach каждый automated профиль по очереди. Manual (`rename`, `format`) пропускаются.

### 4. Проверка результатов

```bash
python3 analyze_results.py results/
```

Или на Windows:

```powershell
python analyze_results.py results
```

## Ручные сценарии

### Repeatability (Test A)

```powershell
.\run_probe_tests.ps1 -Profile baseline_mbr_fat32 -RepeatTwice
python analyze_results.py results\baseline_mbr_fat32.json
```

### Rename

```bash
sudo ./run_vm_suite.sh attach rename_test_base
```

Windows: переименуй том → `.\run_probe_tests.ps1 -Profile rename_test_base_renamed` (или второй scan вручную) → сравни `media_state` vs `media_identity`.

```bash
sudo ./run_vm_suite.sh detach
```

### Format

```bash
sudo ./run_vm_suite.sh attach format_test_base
```

Windows: scan → format тома → scan again. Ожидание: `hardware_stable` тот же, `media_identity` другой.

## Один профиль вручную

```bash
sudo ./run_vm_suite.sh attach gpt_dual_partition
# Windows:
.\run_probe_tests.ps1 -Profile gpt_dual_partition
sudo ./run_vm_suite.sh detach
python3 analyze_results.py results/gpt_dual_partition.json
```

## Что проверяет analyze_results.py

- `BusTypeUsb` (7)
- partition style / counts / volumes
- все 4 hash-поля
- comparison `collision_media_a` vs `collision_media_b`
- comparison `hardware_variant_a` vs `hardware_variant_b`
- repeatability для `baseline_mbr_fat32` (2 observation в одном файле)
- missing profiles из suite

## Troubleshooting

**device_add failed:**

```bash
sudo USB_BUS=ehci.0 ./attach.sh output/baseline_mbr_fat32.img
```

**Probe не видит USB:** образ подключён только через `attach.sh`, не как VirtIO disk.

**exfat / large_4g:** нужны `exfatprogs`, для `large_4g` генерация ~1–2 мин.

## Ограничения VM

Synthetic образы покрывают media-layer и pipeline. Не заменяют bare-metal проверку VID/PID/VPD/collision на реальных флешках.
