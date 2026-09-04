# FlashControl Probe v0.4 — testing tasks

## Цель

Добавить автоматические тесты для текущего USB Research Probe, не изменяя его
архитектуру и JSON-схему без отдельной необходимости.

Основной production-файл:

```text
FlashControlAgent/main.py
```

Тесты должны проверять чистую логику отдельно от реальных Windows API. Реальные
USB/WinAPI проверки оформить отдельным integration-набором, который можно
пропустить на машине без Windows или без подключённой флешки.

## Ограничения

- Сохранять совместимость исходного кода probe с Python 3.4+.
- Не использовать pytest-only возможности, если те же проверки просто сделать
  через `unittest` из stdlib.
- Не добавлять внешние runtime-зависимости агенту.
- Не менять формат Observation, fingerprints и collector results ради удобства
  тестирования.
- Не обращаться к сети.
- Не читать содержимое файлов на USB-накопителях.
- Не выполнять форматирование, переразметку или запись на накопитель.
- Не использовать drive letter и Volume GUID как признаки идентичности.
- Не включать USB hub, PCI/ACPI parents, hostname, session или SID в hardware
  fingerprint.

## Рекомендуемая структура

```text
tests/
  test_helpers.py
  test_storage_parser.py
  test_vpd83_parser.py
  test_partition_parser.py
  test_fingerprints.py
  test_capabilities.py
  test_observation_json.py
  test_windows_integration.py
```

Если такое разделение создаёт много пустых файлов, разрешается объединить чистые
unit-тесты в 2–3 содержательных файла.

## 1. Helpers и structured errors

Проверить:

- `clean_ascii()` для ASCII, NUL termination, пустых значений и не-ASCII bytes;
- `c_string_at_offset()` для корректного, нулевого и выходящего за buffer offset;
- `unique_sorted()` удаляет дубли и пустые значения;
- `error_status()` для:
  - file/path not found;
  - access denied;
  - not supported;
  - invalid parameter;
  - неизвестной ошибки;
- `normalize_collector_error()` не теряет `winerror`, `message`, `status` и
  добавляет имя collector;
- `run_collector()` преобразует неожиданное исключение в `collector_failed` и
  не выбрасывает его наружу.

## 2. Storage Descriptor parser

Сформировать синтетический byte buffer `STORAGE_DEVICE_DESCRIPTOR` и проверить:

- vendor/product/revision/serial offsets;
- bus type и `bus_name`;
- removable media;
- короткий buffer возвращает `invalid_data`, а не вызывает crash;
- offset за границами buffer даёт `null` для соответствующего значения;
- отсутствие serial не ломает collector.

WinAPI `DeviceIoControl` в unit-тестах замокать. Отдельно проверить сам parser,
если для этого понадобится минимальное выделение чистой функции.

## 3. VPD83 parser

Проверить синтетические descriptors:

- один identifier;
- несколько identifiers с `NextOffset`;
- ASCII и бинарное значение;
- `value_hex` стабильно формируется;
- `NextOffset == 0` завершает список;
- слишком маленький `NextOffset` не создаёт бесконечный цикл;
- identifier выходит за buffer — parser безопасно ограничивает чтение;
- count больше фактического количества данных не вызывает crash;
- WinError 87 классифицируется как `unsupported_or_invalid`.

VPD80:

- synthetic SCSI response page `0x80` извлекает Unit Serial Number;
- big-endian page length разбирается корректно;
- unexpected page code, short response, empty serial и длина за границами
  возвращают structured error;
- nonzero SCSI status сохраняет `scsi_status` и `sense_hex`;
- `access_denied` не ломает Observation;
- VPD80 serial участвует в hardware hash, а status/error не участвуют;
- integration test под LocalSystem/сервисом отделён от обычного user-mode run.

## 4. Partition layout parser

Сформировать fixtures для MBR и GPT `DRIVE_LAYOUT_INFORMATION_EX`.

MBR:

- signature/checksum;
- используемый раздел;
- пустые MBR slots с type 0;
- number, offset, length;
- type, boot indicator, recognized partition, hidden sectors;
- partition ID;
- unreasonable count и короткий buffer возвращают structured invalid data.

GPT:

- disk GUID;
- usable offset/length;
- partition type GUID;
- partition GUID;
- attributes;
- UTF-16 partition name;
- zero type GUID помечается как unused.

## 5. PnP и USB evidence

Для синтетической parent chain проверить:

- выбирается настоящий node `USB\\VID_xxxx&PID_yyyy`, а не USB root hub;
- VID/PID извлекаются независимо от регистра;
- последняя часть instance ID сохраняется как serial candidate;
- instance component с `&` помечается `likely_port_specific: true`;
- chain без USB node возвращает `None`;
- hardware/compatible IDs сортируются перед hashing.

## 6. Fingerprint invariants

Создать полный synthetic device record и зафиксировать следующие свойства.

Hardware hash НЕ меняется при изменении:

- physical drive number;
- device interface path;
- drive letters;
- mount paths;
- Volume GUID;
- hostname/session/SID;
- USB hub, PCI и ACPI parents;
- порядка Hardware IDs, Compatible IDs и VPD83 identifiers.

Hardware hash меняется при изменении:

- VID или PID;
- стабильного USB serial candidate;
- Storage Serial;
- vendor/product/revision;
- capacity или sector size;
- VPD83 identifier;
- Hardware IDs настоящего USB/disk node.

Если serial candidate помечен `likely_port_specific`, его изменение НЕ должно
менять hardware hash.

Media hash НЕ меняется при изменении:

- drive letter;
- Volume GUID;
- mount path;
- порядка входных partition/volume records, если их номера и offsets те же.

Media hash меняется при изменении:

- MBR Signature или GPT Disk GUID;
- partition offset/length/type/GUID/attributes;
- filesystem;
- Volume Serial;
- Volume Label.

Observation hash:

- стабилен при одинаковых hardware/media hashes;
- меняется при изменении любого из них.

## 7. Capability model

Проверить:

- `available` отличается от `unsupported` и `collector_failed`;
- VPD83 WinError 87 не считается crash;
- volume collector без найденных томов имеет status `no_volumes`;
- `vpd80` сейчас явно `false` / `not_implemented`;
- top-level capability summary правильно агрегирует несколько devices;
- отсутствие devices не вызывает исключение.

## 8. Observation JSON

Проверить:

- JSON сериализуется с Unicode-значениями;
- scan document содержит `schema_version`, `probe_version`, `scan_id`,
  `generated_at_utc`, `observations`, `scan_capabilities` и `scan_errors`;
- каждая Observation содержит `event_id`, `event_type`, `observed_at_utc`,
  host, session, один device, capabilities, capability status и collector errors;
- `event_id` и `scan_id` являются валидными UUID;
- разные Observation получают разные `event_id`;
- session SID имеет строковый формат `S-1-...`, когда lookup успешен;
- `local_users` отсутствует в host обычной Observation;
- устаревшие volume-поля отсутствуют:
  - `drive_letter`;
  - вложенный `volume`;
  - одиночный `error`;
- присутствуют чистые volume-поля:
  - `volume_guid`;
  - `drive_letters`;
  - `mount_paths`;
  - `partition_number`;
  - `filesystem`;
  - `volume_label`;
  - `volume_serial`.

## 9. Windows integration tests

Пометить/организовать так, чтобы они не мешали обычному unit test run.

На Windows без требования наличия USB проверить:

- SetupAPI enumeration не падает;
- volume enumeration возвращает GUID paths;
- session collector возвращает структурированный результат;
- полный scan выдаёт валидный JSON даже без USB-накопителя.

При наличии тестовой флешки проверить:

- найден BusType USB;
- SetupAPI interface связан с правильным PhysicalDrive;
- PnP chain содержит USBSTOR и USB node;
- VID/PID непустые;
- partition entries связаны с volume partition number;
- два последовательных scan дают одинаковые hardware/media hashes.

Не фиксировать в assertions конкретные VID/PID, serial, PhysicalDrive number,
букву диска или Volume GUID машины разработчика.

## 10. Watch mode

Добавить tests для watch mode:

- начальное подключённое устройство создаёт `snapshot`;
- новый presence key создаёт ровно один `connected`;
- исчезнувший key создаёт ровно один `disconnected` из cached evidence;
- неизменный набор устройств не создаёт повторных событий;
- новый interface, для которого full scan ещё не готов, не кешируется и
  повторно проверяется на следующем цикле;
- каждое watch-событие получает новый UUID;
- hardware/media hashes cached disconnect-события совпадают с последним
  известным connected/snapshot состоянием;
- watch output состоит из отдельных валидных UTF-8 JSON Lines;
- ошибки presence/full rescan не завершают watcher.

Для unit-теста замокать polling/sleep/output; не требовать физически вынимать
USB-накопитель в автоматическом test run.

## 11. Команды и результат

Добавить одну документированную команду запуска, например:

```powershell
python -m unittest discover -s tests -v
```

Для формирования машиночитаемого отчёта по всем пакетам проекта:

```powershell
python tools/test_report.py
```

Отчёт сохраняется в `reports/test-report.json` и содержит сводные счётчики,
результат каждого теста, длительность, причины пропусков и traceback ошибок.
Для запуска Windows integration-набора используйте:

```powershell
python tools/test_report.py --integration
```

После выполнения предоставить:

- список созданных/изменённых файлов;
- количество tests;
- результат unit tests;
- результат integration tests отдельно;
- явно перечислить skipped tests и причину;
- не утверждать совместимость с XP/7 без реального запуска на этих ОС.

## Definition of Done

- Все чистые parser/fingerprint tests проходят без подключённой флешки.
- Ошибочные и короткие buffers не приводят к crash.
- Fingerprint invariants покрыты отдельными assertions.
- Windows integration tests безопасны и read-only.
- Тесты не создают сетевой трафик и ничего не записывают на USB.
- Production JSON не менялся без явно описанной причины.
