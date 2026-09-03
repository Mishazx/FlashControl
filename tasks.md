# Техническое задание: FlashControl

## 1. Назначение проекта

Необходимо разработать корпоративную ИБ-систему **FlashControl** для централизованного обнаружения, идентификации и аудита USB-накопителей, подключаемых к рабочим станциям Windows.

Основная задача системы:

* обнаруживать факт подключения и отключения USB mass-storage устройств;
* собирать максимально возможный набор аппаратных и медиапризнаков устройства;
* различать физически разные флешки, даже если у них совпадают:

  * VID/PID;
  * модель;
  * объём;
  * USB Serial Number;
  * Storage Serial Number;
* выявлять коллизии серийных номеров у дешёвых/китайских USB-контроллеров;
* сохранять историю использования устройства;
* определять, на каких ПК и какими пользователями использовалась флешка;
* централизованно отправлять события на главный сервер;
* при отсутствии прямого маршрута до главного сервера использовать Proxy Collector своей сети;
* поддерживать локальную очередь при отсутствии сети;
* в DEV-режиме разрешать локальный логин/пароль в Web UI;
* в PROD-режиме разрешать Web UI только через Active Directory / корпоративный Identity Provider.

Система является ИБ-средством инвентаризации и расследования.

На первом этапе содержимое файлов флешки **не копируется**.

---

# 2. Поддерживаемые ОС

Целевой зоопарк:

* Windows XP SP3;
* Windows Vista;
* Windows 7 SP1;
* Windows 10;
* Windows 11.

На этапе PoC используется Python.

Требование к исходному коду PoC:

* стремиться к совместимости с Python 3.4+;
* не использовать новые конструкции языка без fallback;
* минимизировать внешние зависимости;
* предпочтительно использовать:

  * Python stdlib;
  * ctypes;
  * Win32 API.

Современные версии Python могут использоваться при разработке на Windows 10/11, но код должен быть написан так, чтобы основные collectors можно было адаптировать к legacy Python.

Production-агент в дальнейшем может быть переписан на C/C++, если Python окажется неприемлем по эксплуатации.

---

# 3. Общая архитектура системы

Архитектура должна поддерживать:

```text
                    ┌─────────────────────┐
                    │ Active Directory /  │
                    │ Corporate IdP       │
                    └──────────┬──────────┘
                               │
                          OIDC/Kerberos
                               │
                               ▼
                         ┌──────────┐
                         │ Web UI   │
                         └────┬─────┘
                              │
                              ▼
                    ┌─────────────────────┐
                    │    MAIN SERVER      │
                    │                     │
                    │ Ingest API          │
                    │ Control API         │
                    │ Identity Engine     │
                    │ Reporting API       │
                    └─────────┬───────────┘
                              │
                         PostgreSQL
                              ▲
                              │
                         mTLS/HTTPS
                              │
               ┌──────────────┴─────────────┐
               │                            │
          direct route                Proxy Collector
               │                            ▲
               │                            │
            Agent                       Agents
```

Логика агента:

```text
USB event
   ↓
полный rescan
   ↓
создание Observation
   ↓
локальная очередь
   ↓
Collector API
   ↓
┌──────────────────────────────────────┐
│ Main в центральной сети или локальный │
│ Proxy Collector на площадке           │
└──────────────────────────────────────┘
```

---

# 4. Этапы реализации

Разработку разделить на milestones.

## Milestone 1 — USB Research Probe

Консольная утилита:

```text
usb_probe.py
```

Она должна:

* обнаруживать USB mass-storage;
* собирать признаки устройства;
* выводить JSON;
* работать без сервера;
* использоваться для сбора исследовательского датасета.

Команды:

```text
python usb_probe.py --scan
python usb_probe.py --scan > result.json
python usb_probe.py --all-disks
```

В дальнейшем:

```text
python usb_probe.py --watch
```

---

## Milestone 2 — Device Fingerprinting

Реализовать сбор аппаратных и медиапризнаков.

Ввести:

```text
hardware evidence
media evidence
context evidence
```

Не считать один serial гарантированным ID.

---

## Milestone 3 — Identity Engine

На сервере реализовать корреляцию observations.

Результат классификации:

```text
SAME
LIKELY_SAME
DIFFERENT
SERIAL_COLLISION
CLONE_SUSPECTED
UNKNOWN
```

---

## Milestone 4 — Agent Queue + Main API

Добавить:

* локальное persistent-хранилище;
* очередь событий;
* retry;
* Main Ingest API.

---

## Milestone 5 — Proxy Collector

Добавить:

* Proxy;
* привязку Proxy к CIDR;
* store-and-forward;
* mTLS;
* пересылку Main Server.

---

## Milestone 6 — Web UI

Реализовать:

* поиск флешек;
* поиск ПК;
* историю событий;
* карточку физического устройства;
* признаки коллизии;
* health агентов/прокси.

---

## Milestone 7 — AD / RBAC

DEV:

```text
local username/password
```

PROD:

```text
Active Directory only
```

Роли через AD-группы.

---

# 5. Текущий этап

Сейчас необходимо работать над:

```text
USB Research Probe v0.4
```

Сеть, Proxy, Main Server и AD пока НЕ являются приоритетом.

Основная цель:

> Проверить на реальных корпоративных компьютерах, какие признаки можно стабильно получить у разных USB-накопителей и позволяют ли они различать одинаковые физические устройства.

---

# 6. Базовая сущность — Observation

Не использовать понятие:

```text
serial == device_id
```

Каждое обнаружение устройства формирует независимый:

```text
Observation
```

Пример:

```json
{
  "schema_version": 1,
  "probe_version": "0.4.0",

  "event_id": "UUID",

  "event_type": "snapshot",

  "observed_at_utc": "...",

  "host": {},

  "session": {},

  "device": {},

  "capabilities": {},

  "collector_errors": []
}
```

---

# 7. Идентификаторы события

Каждое событие должно иметь:

```text
event_id = UUID
```

UUID генерируется на клиенте.

Требование:

```text
event_id
```

должен оставаться неизменным при повторной отправке события.

Это позволит серверу обеспечить идемпотентность:

```sql
UNIQUE(event_id)
```

---

# 8. Host information

Собирать:

```json
{
  "host": {
    "hostname": "...",
    "domain": "...",

    "os": {
      "name": "Windows",
      "release": "...",
      "version": "...",
      "service_pack": "..."
    },

    "architecture": "AMD64",

    "python_version": "...",

    "network_interfaces": []
  }
}
```

Не использовать подключения к:

```text
1.1.1.1
8.8.8.8
```

для определения IP.

Это создаёт ненужный внешний трафик.

Информацию об интерфейсах получать локально.

В дальнейшем отдельно определять:

```text
source IP / interface
```

для маршрута именно к:

```text
Main Server
Proxy
```

---

# 9. User/session information

Основная информация:

```json
{
  "session": {
    "session_id": 1,
    "username": "mihail",
    "domain": "CORP",
    "sid": "S-1-5-21-...",
    "state": "Active"
  }
}
```

Приоритет:

```text
SID > username
```

Переименование пользователя не должно создавать нового субъекта.

Не включать полный список local_users в обычное USB-событие.

Список локальных пользователей можно оставить только для:

```text
--debug
--diagnostics
```

---

# 10. Device Enumerator

Не сканировать только:

```text
PhysicalDrive0 ... PhysicalDrive63
```

как окончательное production-решение.

Для PoC допустимо.

В дальнейшем основным механизмом должен стать:

```text
SetupAPI
```

Использовать:

```text
GUID_DEVINTERFACE_DISK
SetupDiGetClassDevs
SetupDiEnumDeviceInterfaces
SetupDiGetDeviceInterfaceDetail
```

Получить PnP device interface.

---

# 11. PnP Collector

Для каждого обнаруженного USB Storage определить PnP tree.

Требуется получить цепочку примерно:

```text
Physical Disk
   ↓
USBSTOR
   ↓
USB device
   ↓
USB Hub
```

Использовать SetupAPI / Configuration Manager API.

Получать:

```text
device_instance_id
parent_device_instance_id
hardware_ids
compatible_ids
manufacturer
friendly_name
service
class
enumerator
```

Пример:

```json
{
  "pnp": {
    "disk_instance_id":
      "USBSTOR\\DISK&VEN_NETAC&PROD_ONLYDISK...",

    "usb_instance_id":
      "USB\\VID_XXXX&PID_YYYY\\123456",

    "vid": "XXXX",
    "pid": "YYYY",

    "hardware_ids": [],
    "compatible_ids": [],

    "manufacturer": "Netac",
    "service": "USBSTOR"
  }
}
```

---

# 12. VID/PID

Из настоящего USB PnP node получить:

```text
VID
PID
```

Не пытаться получать VID/PID из:

```text
storage.vendor
storage.product
```

Это разные сущности.

Хранить отдельно:

```json
{
  "usb": {
    "vid": "0951",
    "pid": "1666"
  }
}
```

---

# 13. USB serial candidate

Последняя часть:

```text
USB\VID_xxxx&PID_yyyy\SERIAL
```

может выглядеть как serial.

Но нельзя считать её гарантированным серийным номером.

Хранить как evidence:

```json
{
  "value": "...",
  "source": "pnp_usb_instance_id"
}
```

---

# 14. Storage Descriptor Collector

Использовать:

```text
IOCTL_STORAGE_QUERY_PROPERTY
StorageDeviceProperty
```

Получить:

```text
Vendor
Product
Revision
Serial
BusType
RemovableMedia
DeviceType
```

Пример:

```json
{
  "storage": {
    "vendor": "Netac",
    "product": "OnlyDisk",
    "revision": "2.00",
    "serial": "6502711107875132214",
    "bus_type": 7,
    "bus_name": "USB",
    "removable_media": true
  }
}
```

---

# 15. VPD83 Collector

Запрашивать:

```text
StorageDeviceIdProperty
```

Полученные идентификаторы сохранять.

Но отсутствие VPD83 НЕ считать ошибкой всего устройства.

Например:

```json
{
  "vpd83": {
    "status": "unsupported",
    "identifiers": []
  }
}
```

Если WinAPI вернул:

```text
ERROR_INVALID_PARAMETER = 87
```

сохранять:

```json
{
  "code": 87,
  "message": "...",
  "status": "unsupported_or_invalid"
}
```

---

# 16. VPD80

Следующий экспериментальный collector.

Попробовать получить:

```text
SCSI Inquiry
EVPD page 0x80
```

через SCSI pass-through.

Collector должен быть:

```text
optional
```

Ошибка не должна ломать полный scan.

Результат:

```json
{
  "vpd80": {
    "supported": true,
    "serial": "..."
  }
}
```

---

# 17. Geometry Collector

Получать:

```text
IOCTL_DISK_GET_DRIVE_GEOMETRY_EX
```

Хранить:

```text
size_bytes
bytes_per_sector
cylinders
tracks_per_cylinder
sectors_per_track
media_type
```

Критически важное поле:

```text
size_bytes
```

Хранить точное значение:

```text
62914560000
```

а не:

```text
64 GB
```

---

# 18. Partition Collector

Использовать:

```text
IOCTL_DISK_GET_DRIVE_LAYOUT_EX
```

Собирать не только:

```text
partition_count
MBR signature
GPT GUID
```

но и полный список partition entries.

## MBR

Сохранять:

```json
{
  "partition_style": "MBR",

  "mbr_signature": "...",

  "partitions": [
    {
      "number": 1,
      "offset": 1048576,
      "length": 62912462848,
      "mbr_type": 7,
      "boot_indicator": false
    }
  ]
}
```

## GPT

Сохранять:

```json
{
  "partition_style": "GPT",

  "gpt_disk_guid": "...",

  "partitions": [
    {
      "number": 1,
      "offset": "...",
      "length": "...",
      "partition_type_guid": "...",
      "partition_guid": "...",
      "attributes": "..."
    }
  ]
}
```

---

# 19. Volume Collector

Не ограничиваться только буквами:

```text
E:
F:
G:
```

Целевая реализация должна перечислять:

```text
FindFirstVolumeW
FindNextVolumeW
```

и получать:

```text
\\?\Volume{GUID}\
```

Затем определить связь:

```text
Volume
→ PhysicalDrive
→ Partition
```

Получать:

```text
Volume GUID
Drive Letter(s)
Filesystem
Volume Label
Volume Serial
```

Пример:

```json
{
  "volumes": [
    {
      "volume_guid": "\\\\?\\Volume{...}\\",
      "drive_letters": [
        "E:"
      ],

      "partition_number": 1,

      "filesystem": "exFAT",

      "volume_label": "FLASH",

      "volume_serial": "A1B2C3D4"
    }
  ]
}
```

---

# 20. Media identity

Признаки media state:

```text
MBR Signature
GPT Disk GUID
Partition GUID
Partition offsets
Partition lengths
Partition types
Volume Serial
Filesystem
Volume Label
```

Важно:

> media identity может измениться после форматирования или переразметки.

Это НЕ означает, что физическое устройство изменилось.

---

# 21. Hardware identity

Аппаратные evidence:

```text
USB VID
USB PID
USB instance serial candidate
Storage Vendor
Storage Product
Storage Revision
Storage Serial
VPD80
VPD83
Exact Capacity
Sector Size
PnP Hardware IDs
```

Ни одно отдельное поле не считается абсолютным.

---

# 22. Evidence model

Желательно хранить исходные значения вместе с source.

Пример:

```json
{
  "evidence": [
    {
      "name": "serial",
      "value": "6502711107875132214",
      "source": "storage_descriptor",
      "status": "present"
    },

    {
      "name": "vpd83",
      "value": null,
      "source": "storage_device_id_property",
      "status": "unsupported"
    }
  ]
}
```

Различать:

```text
missing
unsupported
access_denied
not_applicable
invalid_data
collector_failed
```

---

# 23. Ошибки WinAPI

Не хранить только локализованное сообщение Windows.

Нужно возвращать:

```json
{
  "collector": "vpd83",
  "winerror": 87,
  "message": "Параметр задан неверно.",
  "status": "unsupported_or_invalid"
}
```

Числовой:

```text
winerror
```

является основным машинным значением.

---

# 24. Hashes

На агенте разрешается рассчитывать вспомогательные hashes.

## hardware_evidence_sha256

Использовать нормализованные:

```text
VID
PID
PnP identifiers
Storage Vendor
Storage Product
Storage Revision
Storage Serial
VPD80
VPD83
Capacity
Sector Size
```

## media_evidence_sha256

Использовать:

```text
MBR/GPT identity
partition layout
partition GUIDs
volume serials
filesystem
```

Не включать:

```text
Drive Letter
```

Потому что одна флешка может быть:

```text
E:
```

на одном ПК и:

```text
G:
```

на другом.

Сортировку partitions выполнять по:

```text
partition_number
offset
```

а не по drive letter.

## observation_sha256

Допускается:

```text
SHA256(
 hardware_evidence_sha256
 +
 media_evidence_sha256
)
```

Но:

> ни один hash не является PhysicalDevice ID.

---

# 25. PhysicalDevice ID

`physical_device_id` назначает только Main Server.

Например:

```text
USB-0000001452
```

или UUID.

Agent не имеет права принимать окончательное решение:

```text
это точно та же физическая флешка
```

Agent собирает evidence.

Server делает correlation.

---

# 26. Identity Engine

На Main Server использовать scoring/rules engine.

Вход:

```text
Observation A
Observation B
```

Выход:

```json
{
  "classification": "LIKELY_SAME",
  "confidence": 0.91,
  "reasons": []
}
```

---

# 27. Пример scoring

Начальная эвристика:

```text
VPD83 exact                         +60
VPD80 exact                         +40
Storage serial exact               +30
USB PnP serial exact               +25
VID/PID exact                      +10
Vendor/Product exact               +5
Revision exact                     +5
Exact capacity                     +10
Sector size                        +2

GPT Disk GUID exact                +25
MBR Signature exact                +15
Partition layout exact             +10
Volume serial exact                +10
```

Эти числа не являются окончательными.

Они должны настраиваться после реального dataset.

---

# 28. Serial collision

Обязательный кейс.

Например:

```text
Flash A:
VID/PID = 1234:5678
Serial  = ABC
Capacity = 64 GB

Flash B:
VID/PID = 1234:5678
Serial  = ABC
Capacity = 64 GB
```

Но:

```text
MBR A != MBR B
Volume A != Volume B
```

Нельзя автоматически считать их одной флешкой.

Статус:

```text
SERIAL_COLLISION
```

---

# 29. Одновременное использование

Очень сильное правило.

Если:

```text
Device identity X
```

наблюдается:

```text
10:31 PC-MSK-001
```

и одновременно:

```text
10:31 PC-SPB-007
```

и физическая перемещаемость между точками невозможна, то:

```text
same claimed identity
≠
same physical device
```

Создать:

```text
SERIAL_COLLISION
```

Это один из главных способов выявления клонированных serial.

---

# 30. Clone suspected

Если совпадают:

```text
hardware identifiers
+
media identifiers
+
filesystem identity
```

но устройство одновременно появляется на физически разных машинах:

```text
CLONE_SUSPECTED
```

В будущем можно добавлять дополнительные признаки.

---

# 31. Format scenario

Обязательный тест:

```text
Flash A до format
Flash A после format
```

Ожидаемый результат:

```text
hardware evidence:
практически не изменилось

media evidence:
изменилось
```

Identity Engine должен вернуть:

```text
LIKELY_SAME
```

а не новый PhysicalDevice.

---

# 32. Local queue

После Research Probe реализовать локальную очередь.

Предпочтительно:

```text
SQLite
```

Таблица:

```sql
events
------
id
event_id
created_at
event_type
payload
status
attempts
next_attempt_at
last_error
```

Статусы:

```text
pending
sending
sent
dead_letter
```

Алгоритм:

```text
USB event
    ↓
Observation
    ↓
SQLite COMMIT
    ↓
network send
    ↓
HTTP ACK
    ↓
mark sent
```

Событие нельзя удалять до подтверждения сервера.

---

# 33. Event detection

Production Agent должен работать как Windows Service.

События:

```text
DEVICE ARRIVAL
DEVICE REMOVE
```

Обработчик PnP не выполняет тяжёлое сканирование.

Правильно:

```text
PnP event
   ↓
enqueue rescan
   ↓
debounce
   ↓
worker
   ↓
full snapshot
```

Debounce ориентировочно:

```text
500–1500 ms
```

---

# 34. Snapshot diff

Не считать PnP event единственным источником истины.

Хранить предыдущий snapshot:

```text
A B C
```

Новый:

```text
A B C D
```

Значит:

```text
D connected
```

Если:

```text
A B C D
```

стало:

```text
A B C
```

значит:

```text
D disconnected
```

---

# 35. Transport

Интерфейс:

```text
ITransport
```

Логика:

```text
POST в единственный настроенный Collector API
  ↓
HTTP ACK → удалить из локальной очереди
ошибка   → сохранить в локальной очереди и повторить с backoff
```

---

# 36. Проверка Collector

Не использовать:

```text
ping
```

как единственный критерий.

Проверять реальный application endpoint Collector:

```text
HTTPS /health
```

или соединение с Ingest API.

Результат кешировать на ограниченное время.

---

# 37. Адрес Collector

У агента ровно один адрес Collector API. Он не знает, является ли получатель
Main Server или Proxy Collector, и не содержит списка Proxy/CIDR. Для каждой
площадки адрес задаётся при установке либо через DNS: в центральной сети он
указывает на Main, в изолированной или промежуточной — на локальный Proxy.

---

# 38. Proxy Collector

Proxy НЕ является:

```text
HTTP proxy
SOCKS proxy
general network relay
```

Это специализированный collector.

Разрешённые endpoints:

```text
POST /api/v1/events
POST /api/v1/heartbeat
```

Proxy:

```text
Agent
   ↓
validate
   ↓
persist
   ↓
202 Accepted
   ↓
background forwarding
   ↓
Main
```

---

# 39. Proxy network restriction

Proxy должен принимать клиентов только разрешённых сетей.

Но нельзя использовать только:

```text
source IP
```

Проверять совокупность:

```text
client certificate
registered computer_id
source CIDR
proxy/site assignment
```

---

# 40. Agent authentication

Agent не использует пользовательский login/password.

Production:

```text
mTLS
```

Каждому Agent:

```text
client certificate
```

Private key хранится в Windows Machine Certificate Store.

---

# 41. Legacy Windows

XP/Vista не должны заставлять ослаблять TLS Main Server.

Предпочтительная архитектура:

```text
XP / Vista
     ↓
Legacy/local Proxy
     ↓
modern TLS/mTLS
     ↓
Main
```

Transport слой должен быть заменяемым.

---

# 42. Main Server

Логически:

```text
Ingest API
Identity Engine
Control API
Reporting API
Auth module
```

На первом этапе можно разместить одним приложением.

Не вводить Kafka/RabbitMQ без доказанной необходимости.

---

# 43. Database

Предпочтительно:

```text
PostgreSQL
```

Основные таблицы:

```text
computers
agents
device_observations
physical_devices
device_identity_links
device_media_states
usb_events
proxies
proxy_networks
sites
users
roles
audit_log
```

---

# 44. physical_devices

Пример:

```text
id
created_at
first_seen_at
last_seen_at
status
identity_confidence
```

---

# 45. device_observations

Сохранять RAW observation.

```text
id
event_id
physical_device_id nullable
computer_id
observed_at
raw_json
hardware_hash
media_hash
```

Важно сохранять исходный JSON, чтобы позже можно было пересчитать Identity Engine.

---

# 46. Media State

У одной физической флешки могут быть разные состояния:

```text
PhysicalDevice #145
   │
   ├── Media State #1 FAT32
   │
   ├── Media State #2 NTFS
   │
   └── Media State #3 GPT/exFAT
```

Форматирование не создаёт новый PhysicalDevice.

---

# 47. Heartbeat

Agent периодически отправляет:

```json
{
  "computer_id": "...",
  "agent_version": "...",
  "current_ips": [],
  "queue_size": 0,
  "selected_route": "direct",
  "proxy_id": null,
  "timestamp": "..."
}
```

---

# 48. Web UI

Нужны страницы:

```text
Dashboard
Computers
USB Devices
Events
Proxies
Sites
Collisions
Audit
Settings
```

---

# 49. USB Device Card

Показывать:

```text
Physical Device ID
First Seen
Last Seen
Confidence
Vendor/Product
VID/PID
Serial values
Capacity
Known media states
Used on computers
Used by users
Serial collisions
Clone warnings
Raw observations
```

---

# 50. DEV authentication

DEV mode:

```yaml
environment: development

authentication:
  provider: local
```

Разрешить:

```text
login/password
```

Пароль хранить только как безопасный password hash.

---

# 51. PROD authentication

PROD:

```yaml
environment: production

authentication:
  provider: active-directory
```

Local login должен быть полностью отключён.

Предпочтение:

```text
OIDC / AD FS / corporate IdP
```

или при необходимости:

```text
Kerberos / Windows Integrated Authentication
```

Не проектировать приложение вокруг ручного ввода AD password + LDAP Bind, если есть нормальный federation mechanism.

---

# 52. RBAC

Пример групп:

```text
FlashControl-Admins
FlashControl-Security
FlashControl-Auditors
FlashControl-MSK
FlashControl-SPB
```

Пример прав:

```text
Admin:
full access

Security:
all USB data

Auditor:
read-only

Site role:
only assigned sites/subnets
```

---

# 53. Audit Log

Все административные действия:

```text
user
timestamp
action
object
old value
new value
source IP
```

---

# 54. Privacy

На первом этапе НЕ собирать:

```text
file contents
file hashes
documents
file bodies
```

Опциональный будущий режим:

```yaml
collection:
  file_inventory: false
  file_hashes: false
```

Если понадобится file inventory:

собирать только по отдельной политике.

---

# 55. Project structure PoC

Рекомендуемая структура:

```text
FlashControl/
│
├── agent/
│   ├── main.py
│   │
│   ├── collectors/
│   │   ├── storage.py
│   │   ├── geometry.py
│   │   ├── partition.py
│   │   ├── volume.py
│   │   ├── pnp.py
│   │   ├── vpd.py
│   │   ├── host.py
│   │   └── session.py
│   │
│   ├── identity/
│   │   ├── normalize.py
│   │   └── hashes.py
│   │
│   ├── windows/
│   │   ├── kernel32.py
│   │   ├── setupapi.py
│   │   ├── cfgmgr32.py
│   │   ├── wtsapi.py
│   │   └── structures.py
│   │
│   └── models/
│       └── observation.py
│
├── tests/
│
├── samples/
│
└── README.md
```

Не оставлять весь код в одном:

```text
main.py
```

---

# 56. Separation of collectors

Каждый collector должен:

```text
получить вход
попробовать собрать данные
вернуть result
вернуть structured error
```

Ошибка одного collector не должна ломать весь scan.

Пример:

```python
result = collector.collect(device)
```

Логически:

```text
CollectorResult:
    supported
    success
    data
    error
```

---

# 57. Capability model

JSON должен показывать:

```json
{
  "capabilities": {
    "storage_descriptor": true,
    "geometry": true,
    "partition_layout": true,
    "volume_information": true,
    "pnp_tree": true,
    "vpd80": false,
    "vpd83": false
  }
}
```

Это необходимо для XP/Vista/7/10/11.

---

# 58. Нельзя путать

Разделять:

```text
not supported
```

и:

```text
failed
```

Например:

```text
vpd83 unsupported
```

не равно:

```text
agent bug
```

---

# 59. JSON schema version

Каждый payload:

```json
{
  "schema_version": 1
}
```

При несовместимом изменении:

```text
schema_version = 2
```

---

# 60. Probe version

Каждый результат:

```text
probe_version
```

например:

```text
0.4.0
```

---

# 61. Test dataset

Создать каталог:

```text
samples/
```

Структура:

```text
samples/
  flash_A/
    pc1_port1_1.json
    pc1_port1_2.json
    pc1_port2.json
    pc2.json

  flash_B_same_model/
    pc1.json

  flash_C/
    ...
```

---

# 62. Обязательные тесты PoC

## Test A — repeatability

Одна флешка.

Три раза:

```text
scan
scan
scan
```

Hardware evidence должен быть одинаковым.

---

## Test B — other USB port

Та же флешка в другом USB-port.

Hardware identity должна остаться одинаковой.

Не использовать USB port number как идентификатор устройства.

---

## Test C — other computer

Та же флешка на другом ПК.

Hardware evidence должен максимально совпасть.

---

## Test D — identical model

Две физически разные флешки:

```text
same vendor
same model
same capacity
```

Проверить:

```text
serial
PnP ID
VPD80
VPD83
MBR/GPT
Volume Serial
partition layout
```

---

# 63. Критический PoC Test

Особенно нужны:

```text
2–10 одинаковых дешёвых флешек одной партии
```

Если:

```text
hardware evidence
```

полностью совпадает:

зафиксировать это как:

```text
hardware_collision
```

и проверить media/context признаки.

---

# 64. Format test

Флешка до format:

```text
A_before.json
```

после format:

```text
A_after.json
```

Ожидание:

```text
hardware hash == same
media hash != same
```

---

# 65. Repartition test

Удалить/создать раздел.

Ожидание:

```text
hardware stable
media changed
```

---

# 66. Simultaneous collision test

Если возможно:

две одинаковые флешки с одинаковым serial одновременно подключить к двум ПК.

Это ключевой тест будущего Identity Engine.

---

# 67. Acceptance criteria v0.4

v0.4 считается готовой, если:

* scan стабильно выполняется на Windows 10/11;
* есть экспериментальная проверка Windows 7;
* есть проверка legacy compatibility;
* USB mass storage определяется;
* Storage Descriptor собирается;
* PnP chain собирается;
* VID/PID собираются;
* geometry собирается;
* partition entries собираются;
* volumes собираются;
* user SID собирается;
* VPD83 отсутствие не ломает scan;
* WinAPI errors структурированы;
* нет обращения к публичным IP;
* hardware/media hashes стабильны;
* вывод является валидным JSON;
* ошибка одного collector не рушит весь результат.

---

# 68. Definition of Done Research Phase

Research Phase завершён, когда имеется реальный dataset минимум:

```text
10–20 USB devices
```

из них желательно:

```text
5+ одинаковой модели/партии
```

и документирована таблица:

```text
field
available %
stable on same device %
different between identical devices %
```

Пример:

```text
Storage Serial:
available 95%
stable 100%
unique 70%

VPD83:
available 15%
stable 100%
unique 90%

MBR Signature:
available 90%
stable until repartition
unique 95%
```

Только после этого утверждать окончательный Identity Algorithm.

---

# 69. Не делать пока

До завершения Research Phase не тратить время на:

```text
Kafka
Kubernetes
microservices
сложный frontend
ML identification
полную AD integration
production installer
production TLS compatibility XP
```

---

# 70. Ближайшая задача Codex

На основе существующего PoC привести проект к архитектуре v0.4.

Последовательность:

```text
1. Провести code review существующего main.py.

2. Не ломая рабочую функциональность,
   разнести код по modules.

3. Исправить utcnow deprecation.

4. Удалить внешние UDP probes к
   1.1.1.1 / 8.8.8.8.

5. Добавить structured WinError.

6. Добавить SetupAPI Device Enumerator.

7. Связать PhysicalDrive с PnP node.

8. Получить USB parent node.

9. Извлечь VID/PID.

10. Сохранить PnP instance IDs.

11. Добавить Hardware IDs / Compatible IDs.

12. Добавить partition entries.

13. Улучшить Volume Collector.

14. Получить SID активного пользователя.

15. Пересчитать hardware/media fingerprints
    на новых evidence.

16. Добавить capabilities.

17. Добавить unit tests там,
    где WinAPI не требуется.

18. Добавить README с командами.

19. Не добавлять networking/backend.

20. Сохранить Python stdlib-only,
    если это технически возможно.
```

---

# 71. Требования к работе Codex

Перед изменением файлов:

1. изучить существующий проект;
2. показать краткий список обнаруженных модулей;
3. определить, какие части текущей реализации можно сохранить;
4. не переписывать рабочий код без причины.

После каждого milestone:

* запускать syntax check;
* запускать существующие tests;
* добавлять новые tests;
* показывать список изменённых файлов;
* кратко описывать, что сделано;
* явно перечислять, что ещё не реализовано.

---

# 72. Требования к совместимости

Не использовать без крайней необходимости:

```text
Python 3.10-only syntax
match/case
dataclass без fallback
typing features новых Python
f-string, если требуется реальный запуск на Python 3.4
pathlib-only решения
```

Если проект действительно должен запускаться на Python 3.4:

использовать syntax совместимый с 3.4.

При необходимости modern-dev код и legacy compatibility можно разделить.

---

# 73. Требования к безопасности

Agent:

* работает с минимально необходимыми правами;
* не читает содержимое файлов;
* не изменяет флешку;
* не создаёт marker-файлы;
* не выполняет произвольный код;
* не получает секреты пользователя;
* не хранит AD password;
* не делает внешних интернет-запросов.

---

# 74. Будущий режим корпоративного marker

Не реализовывать сейчас.

В будущем возможно:

```text
signed corporate device marker
```

на разрешённых корпоративных носителях.

Он должен использоваться только как дополнительный evidence.

Никогда не считать файл-маркер единственным идентификатором.

---

# 75. Главный принцип проекта

Главный принцип:

```text
Collect facts on endpoint.
Correlate identity centrally.
```

То есть:

```text
Agent:
что я вижу?

Main:
что это за физическое устройство?
```

А не:

```text
Agent:
serial совпал → это та же флешка
```

---

# 76. Главная цель текущего PoC

Получить ответ на вопрос:

> Можем ли мы в реальных корпоративных сетях и на реальном парке Windows XP/Vista/7/10/11 собрать достаточно независимых признаков USB mass-storage, чтобы отличать физически разные устройства даже при одинаковых или некорректных серийных номерах?

Все решения текущего этапа должны быть направлены именно на получение достоверного ответа на этот вопрос.

---

# 77. Формат отчёта Codex после проверки проекта

После анализа существующего репозитория Codex должен вернуть:

```text
PROJECT CHECKUP

Current state:
- ...

Already implemented:
- ...

Partially implemented:
- ...

Missing:
- ...

Technical debt:
- ...

Compatibility risks:
- ...

Security/privacy issues:
- ...

Next milestone:
- v0.4

Files to modify:
- ...

Files to create:
- ...

Tests to add:
- ...

Do not implement yet:
- ...

Recommended implementation order:
1.
2.
3.
...
```

После checkup можно приступать к реализации ближайшего milestone.
