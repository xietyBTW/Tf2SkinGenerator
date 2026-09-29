/*
 * Английские подписи интерфейса.
 *
 * Ключ — русский текст ровно в том виде, в каком он написан в разметке или в
 * коде. Так сделано намеренно: подписи разбросаны по двадцати файлам и по
 * сотне мест в index.html, и перевод на ключи означал бы правку каждого из
 * них — с риском разъехаться при первой же следующей правке. Здесь же
 * незнакомая строка просто остаётся русской, и это видно на экране.
 *
 * `{}` — подстановка. Такие ключи узнают собранную строку целиком («Собрано:
 * mod.vpk»), а не её кусок. Поэтому строка с подстановкой в коде собирается
 * ОДНИМ шаблоном (`Разбор ${name}…`), а не склейкой кусков: кусок «Разбор»
 * словарь нашёл бы, а склеенную строку на экране — уже нет.
 *
 * Сообщения Python (ошибки сеанса и воркеров) тоже здесь: они приходят
 * готовым текстом и попадают в те же подписи, что и всё остальное.
 *
 * Чего тут нет и быть не должно: имён предметов, материалов и файлов. Их
 * отдаёт Python уже на нужном языке (см. `api._lang`).
 */

export const EN = {
  // ── Шапка, разделы, ряд действий ──────────────────────────────────────
  'Оружие': 'Weapons',
  'Шапки': 'Cosmetics',
  'Частицы': 'Particles',
  'Диагностика': 'Diagnostics',
  'Настройки': 'Settings',
  'Инструменты': 'Tools',
  'Сменить предмет': 'Change item',
  'Извлечь модель (SMD)': 'Extract model (SMD)',
  'Экспорт UV-шаблона (PNG)': 'Export UV template (PNG)',
  'Извлечь оригинальную текстуру': 'Extract original texture',
  'Собрать несколько VPK в один': 'Merge several VPKs into one',
  'Открыть PCF с диска…': 'Open PCF from disk…',
  'Сохранить PCF…': 'Save PCF…',
  'Справочник параметров (JSON)…': 'Parameter reference (JSON)…',
  'Справочник для ИИ (с заданием)…': 'Reference for AI (with a task)…',
  'Собрать VPK': 'Build VPK',
  'Журнал': 'Log',
  'Очистить': 'Clear',

  // ── Вид предмета: вкладки, команды, кнопки под альбомом ────────────────
  'Вместе': 'Together',
  'Текстура': 'Texture',
  'Текстура:': 'Texture:',
  'текстура': 'texture',
  'Модель': 'Model',
  'От первого лица': 'First person',
  'Насмешка': 'Taunt',
  'Сборка насмешки…': 'Building the taunt…',
  'Насмешку показывает только реквизит': 'Only a taunt prop can show a taunt',
  'Выберите предмет': 'Select an item',
  'Карты материала': 'Material maps',
  'Прочее': 'Other',
  'Добавить материал': 'Add material',
  'Сохранить работу': 'Save work',
  'Вернуть правки': 'Restore edits',
  'Забыть правки': 'Discard edits',
  'Удалить работу': 'Delete work',
  'Заменить модель': 'Replace model',
  'Редактировать QC': 'Edit QC',
  'Сделать командным': 'Make team-colored',
  'Разделить на части': 'Split into parts',
  'Убрать свою модель': 'Remove custom model',
  // Что заменить: оружие или его гирлянду
  'Что заменить?': 'What to replace?',
  'Что вернуть к игровому?': 'What to restore to stock?',
  'Выбрать файл': 'Choose file',
  'Само оружие': 'The weapon itself',
  'Праздничная гирлянда': 'Festive lights',
  'Гирлянда фестивайзера': 'Festivizer lights',
  'Своя гирлянда': 'Custom lights',
  'Своя гирлянда; текстур из файла: {}': 'Custom lights; textures from the file: {}',
  'Гирлянда снова стоковая': 'Lights are stock again',
  'SMD не читается: нет треугольников': 'The SMD cannot be read: it has no triangles',
  // Подгонка импортированной модели (OBJ/GLB)
  'Масштаб': 'Scale',
  'Сдвиг': 'Offset',
  'Вокруг X': 'Around X',
  'Вокруг Y (вверх)': 'Around Y (up)',
  'Вокруг Z (вдоль ствола)': 'Around Z (along the barrel)',
  'Подгонка есть только у импортированной модели': 'Fitting is only for imported models',
  'упрощено: {} → {} треугольников': 'simplified: {} → {} triangles',
  'Среди выбранных файлов нет модели': 'None of the selected files is a model',
  'Масштабировать': 'Scale & fit',
  'Подгонка': 'Fitting',
  'Двигать (G)': 'Move (G)',
  'Вращать (R)': 'Rotate (R)',
  'Масштаб (S)': 'Scale (S)',
  'Двигать': 'Move',
  'Вращать': 'Rotate',
  'Сбросить подгонку': 'Reset fitting',
  'Поворот, °': 'Rotation, °',
  'Y (вверх)': 'Y (up)',
  'Z (вдоль ствола)': 'Z (along the barrel)',
  'Подогнать размер, поворот и положение по призраку оригинала':
    'Fit size, rotation and position to the ghost of the original',
  'SMD из Blender или OBJ/GLB с сайта; MTL и текстуры выберите вместе с моделью':
    'SMD from Blender or OBJ/GLB from a website; pick the MTL and textures together with the model',
  'текстур из файла: {}': 'textures from the file: {}',
  'Упрощение недоступно: нет tools/meshoptimizer/meshoptimizer.dll':
    'Simplification unavailable: tools/meshoptimizer/meshoptimizer.dll is missing',
  'OBJ повреждён: грань ссылается на несуществующую вершину':
    'OBJ is damaged: a face references a missing vertex',
  'В файле нет ни одного треугольника': 'The file has no triangles',
  'Формат {} не поддерживается: нужен OBJ, GLB или glTF':
    'Format {} is not supported: use OBJ, GLB or glTF',
  'Рядом с glTF нет файла {} — сохраните модель как GLB (один файл)':
    'File {} is missing next to the glTF — save the model as GLB (single file)',
  '{} треугольников — лимит игры {}. Упростите модель в редакторе':
    '{} triangles — the game limit is {}. Simplify the model in an editor',
  '{} вершин (после разрезания по швам и рёбрам) — лимит игры {}. Упростите модель в редакторе':
    '{} vertices (after splitting by seams and hard edges) — the game limit is {}. Simplify the model in an editor',
  '{} материалов — лимит игры {}. Объедините материалы в редакторе':
    '{} materials — the game limit is {}. Merge materials in an editor',
  'glTF повреждён или использует расширение, которое не поддерживается ({})':
    'glTF is damaged or uses an unsupported extension ({})',
  'OBJ повреждён: строка «{}» ({})': 'OBJ is damaged: line «{}» ({})',
  'glTF не разобран: {}': 'glTF could not be parsed: {}',
  'GLB без JSON-описания': 'GLB without a JSON chunk',
  'glTF ссылается на буфер, которого нет в файле': 'glTF references a buffer that is not in the file',
  'Стиль': 'Style',
  'Стиль шапки': 'Cosmetic style',
  'Положить работу в раздел «Кастомный мод»':
    'Put this work into the “Custom mod” section',
  'У предмета остались отложенные правки': 'This item has edits set aside',
  'Удалить сохранённые правки этого предмета':
    'Delete the saved edits of this item',
  'С красками шапка красится командным цветом, как стоковая':
    'With paints the cosmetic takes the team color, like a stock one',
  'Вернуть игровую модель вместо своей': 'Bring back the game model',
  'Настройки этой текстуры': 'Settings for this texture',
  'Убрать материал из стиля': 'Remove the material from the style',

  // ── Каталог ───────────────────────────────────────────────────────────
  'Категория': 'Category',
  'Назад': 'Back',
  'Вперёд': 'Forward',
  'Класс': 'Class',
  'Тип': 'Type',
  'Скрыть': 'Hide',
  'Куда': 'Where',
  'Коллекция': 'Collection',
  'Все коллекции': 'All collections',
  'Краска': 'Paint',
  'Без краски': 'No paint',
  'Как выглядит с краской из игры': 'How it looks with a paint from the game',
  'Закрыть': 'Close',
  'Название или файл': 'Name or file',
  'Все': 'All',
  'все классы': 'all classes',
  'предмет': 'item',
  'предмета': 'items',
  'предметов': 'items',
  'класс': 'class',
  'класса': 'classes',
  'классов': 'classes',
  'стиль': 'style',
  'стиля': 'styles',
  'стилей': 'styles',
  'Ничего не найдено — попробуйте изменить фильтр или запрос.':
    'Nothing found — try another filter or query.',
  'Для этой категории список ещё не подключён.':
    'The list for this category is not wired up yet.',
  'Раздел «{}» ещё не подключён.': 'Section “{}” is not wired up yet.',
  'Эффект': 'Effect',
  'Файл не выбран': 'No file selected',
  'Выберите систему частиц.': 'Select a particle system.',

  // ── Библиотека модов и работы ─────────────────────────────────────────
  'Свои работы и моды из VPK. Предмет из списка оружия открывается игровым — сохранённая работа открывается отсюда.':
    'Your saved works and VPK mods. An item picked from the weapons list opens as it is in the game — a saved work opens from here.',
  'Открыть VPK-мод…': 'Open a VPK mod…',
  'файл с диска': 'file from disk',
  'Убрать из библиотеки (исходный файл останется)':
    'Remove from the library (the source file stays)',
  'Убрать мод из библиотеки': 'Remove the mod from the library',
  '{}\nУдалится копия в библиотеке. Исходный файл, который вы открывали, останется на месте.': '{}\nThe library copy will be deleted. The original file you opened stays where it is.',
  'Убрать': 'Remove',
  'сегодня': 'today',
  'вчера': 'yesterday',
  '{} день назад': '{} day ago',
  '{} дня назад': '{} days ago',
  '{} дней назад': '{} days ago',
  'сохранённая работа': 'saved work',
  'Открываю работу…': 'Opening the work…',
  'Разбор {}…': 'Reading {}…',
  'мод из VPK': 'VPK mod',
  'Работа сохранена — она в разделе «Кастомный мод»':
    'Work saved — it is in the “Custom mod” section',
  'Отложенные правки вернулись': 'The edits you set aside are back',
  'Правки удалены': 'Edits deleted',

  // ── Сборка ────────────────────────────────────────────────────────────
  'Разрешение': 'Resolution',
  '256 × 256 · спрей': '256 × 256 · spray',
  '512 × 512 · обычное': '512 × 512 · normal',
  '1024 × 1024 · высокое': '1024 × 1024 · high',
  '2048 × 2048 · ультра': '2048 × 2048 · ultra',
  'Формат VTF': 'VTF format',
  'Имя VPK': 'VPK name',
  // Ключ — то, что видно в узле: сущности разметки браузер уже раскрыл.
  'Не более 50 символов, без \\ / : * ? " < > |':
    'Up to 50 characters, no \\ / : * ? " < > |',
  'Флаги VTF': 'VTF flags',
  'Особые флаги': 'Advanced flags',
  'Найти автоматически': 'Detect automatically',
  'Игра найдена: ': 'Game found: ',
  'Найдено копий игры: ': 'Game copies found: ',
  ', взял первую': ', using the first one',
  'Игра не нашлась — укажите папку вручную':
    'The game was not found - set the folder manually',
  'Где установлена TF2?': 'Where is TF2 installed?',
  'Нашёл игру здесь. Сохранить этот путь?':
    'Found the game here. Save this path?',
  'Найти игру сам не смог. Вставьте путь к папке игры.':
    'Could not find the game. Paste the path to the game folder.',
  'Особые флаги VTF': 'Advanced VTF flags',
  'Флаги VTF, которые цветному скину либо безразличны (фильтрацию решает клиент), либо относятся к другому виду текстур, либо вредны: SSBump объявляет текстуру бампмапом':
    'VTF flags that a color skin either does not care about (the client decides filtering), or that belong to a different kind of texture, or that do harm: SSBump declares the texture a bump map',
  'Опции': 'Options',
  'Гамма-коррекция': 'Gamma correction',
  'Изолировать плечи': 'Isolate shoulders',
  'Краски из игры': 'Game paints',
  'Останавливаю сборку…': 'Stopping the build…',
  'Сборка…': 'Building…',
  'Ошибка сборки': 'Build failed',
  'Чем красить «{}»': 'What to put on “{}”',
  'Своей текстуры для этого материала нет.':
    'There is no custom texture for this material.',
  'Оставить игровую': 'Keep the game one',
  'Материал не попадёт в мод — в игре останется стоковый':
    'The material is left out of the mod — the stock one stays in the game',
  'Скопировать главную': 'Copy the main one',
  'На этот материал ляжет та же текстура, что и на основной':
    'This material gets the same texture as the main one',
  'Выбрать файл…': 'Pick a file…',
  'Своя картинка именно для этого материала':
    'A custom image just for this material',
  'Своя модель для части «{}»': 'Custom model for the “{}” part',
  'разбитое состояние': 'the broken state',
  'состояние после взрыва': 'the state after the explosion',
  'Это {}: игра переключает на него сама. Основную часть заменила ваша модель; чем собрать эту?':
    'This is {}: the game switches to it by itself. Your model replaced the main part; what should this one be built from?',
  'Основную часть заменила ваша модель; чем собрать эту?':
    'Your model replaced the main part; what should this one be built from?',
  'Часть останется такой, как в игре': 'The part stays as it is in the game',
  'Выбрать файл SMD…': 'Choose an SMD file…',
  'Своя геометрия этой части; кости и материалы возьмутся из игровой':
    'Your own geometry for this part; bones and materials come from the game one',
  'И так для остальных материалов': 'Same for the rest of the materials',
  'Ответить': 'Answer',
  'Собрано: {}': 'Built: {}',
  'Сборка успешно завершена: {}': 'Build finished: {}',
  'Ошибка сборки: {}': 'Build failed: {}',

  // ── Состояние снизу ───────────────────────────────────────────────────
  'Готово': 'Ready',
  'TF2 найден · tf/tf2_misc_dir.vpk': 'TF2 found · tf/tf2_misc_dir.vpk',
  'TF2 не найдена — укажите папку игры в настройках':
    'TF2 not found — set the game folder in the settings',
  'TF2 найдена · ': 'TF2 found · ',
  ' · Crowbar готов': ' · Crowbar ready',
  ' · Crowbar НЕ НАЙДЕН': ' · Crowbar NOT FOUND',
  'Параметры': 'Parameters',
  'Нет связи с Python: {}': 'No connection to Python: {}',
  'неизвестная ошибка': 'unknown error',

  // ── Настройки ─────────────────────────────────────────────────────────
  'Папка игры': 'Game folder',
  'Папка экспорта': 'Export folder',
  'Формат извлечения': 'Extraction format',
  'Язык приложения': 'Application language',
  'Тема приложения': 'Application theme',
  'Обход sv_pure': 'sv_pure bypass',
  'Вести черновик правок': 'Keep a draft of edits',
  'Закрепить панели': 'Pin the panels',
  'Группировать дерево частиц': 'Group the particle tree',
  'Хранить временные файлы при ошибке': 'Keep temp files on failure',
  'Отладочный режим': 'Debug mode',
  'Скрытые материалы': 'Hidden materials',
  'Совпадение по части имени: «head» скроет и «scout_head_red». Знак «=» в начале требует точного имени. Скрытые материалы не показываются в альбоме; в мод они пишутся с игровой текстурой.':
    'Matched by part of the name: “head” also hides “scout_head_red”. A leading '
    + '“=” demands the exact name. Hidden materials are kept out of the album; '
    + 'they go into the mod with their in-game texture.',
  'по одному в строке или через запятую': 'one per line or comma-separated',
  'Очистить кэш моделей': 'Clear the model cache',
  'Удалить черновики…': 'Delete drafts…',
  'Поддержать автора': 'Support the author',
  'Сохранить': 'Save',
  'Отмена': 'Cancel',
  'Применить': 'Apply',
  'Настройки сохранены': 'Settings saved',
  'для закреплённых панелей нужно окно шире 1100 px':
    'pinned panels need a window wider than 1100 px',
  'Черновик пишется молча и предлагается кнопкой «Вернуть правки». В раздел «Кастомный мод» работа попадает только по кнопке «Сохранить работу»':
    'The draft is written silently and offered by the “Restore edits” button. A work reaches the “Custom mod” section only through “Save work”',
  'Каталог и параметры прибиты к краям, а не вызываются поверх. Нужно окно шире 1100 px':
    'The catalog and parameters are pinned to the edges instead of opening on top. Needs a window wider than 1100 px',
  'Сейчас в кэше {}. Кэш ускоряет повторную сборку того же оружия — после очистки первая сборка каждого будет медленнее.': 'The cache now holds {}. It speeds up rebuilding the same weapon — after clearing, the first build of each will be slower.',
  'Кэш очищен, записей удалено: {}': 'Cache cleared, entries removed: {}',
  'МБ': 'MB',
  'КБ': 'KB',
  'пусто': 'empty',
  'нет': 'none',
  'черновик': 'draft',
  'черновика': 'drafts',
  'черновиков': 'drafts',
  'Черновиков нет': 'There are no drafts',
  'Удалить черновики': 'Delete drafts',
  'Это молчаливые записи автосохранения — работы, сохранённые кнопкой, здесь не показаны и не пострадают. Снимите отметку с того, что нужно оставить.':
    'These are the silent autosave records — works saved with the button are not listed here and will not be touched. Uncheck whatever you want to keep.',
  'Черновиков удалено: {}': 'Drafts deleted: {}',

  // ── Диагностика ───────────────────────────────────────────────────────
  'Диагностика мода': 'Mod diagnostics',
  'Проверяет собранный VPK: пути в VMT, форматы VTF, структуру мода — то, что в игре превращается в фиолетовую текстуру или невидимую модель.':
    'Checks a built VPK: VMT paths, VTF formats, mod structure — the things that turn into a purple texture or an invisible model in the game.',
  'Выбрать VPK…': 'Pick a VPK…',
  'Выберите собранный VPK-мод': 'Select a built VPK mod',
  'Проверка…': 'Checking…',
  'Проверка не удалась': 'The check failed',
  'Проблем не найдено': 'No problems found',
  'Ошибок: {} · предупреждений: {}': 'Errors: {} · warnings: {}',
  'Что делать: {}': 'What to do: {}',

  // ── Редактор VMT и QC ─────────────────────────────────────────────────
  'Материал': 'Material',
  'Ctrl+S — сохранить · Esc — закрыть': 'Ctrl+S — save · Esc — close',
  'Как в игре': 'As in the game',
  '● Есть несохранённые изменения': '● Unsaved changes',
  '✓ Используется свой VMT': '✓ A custom VMT is in use',
  'Показывается оригинал из игры': 'Showing the game original',
  'Правка удалена, показан игровой оригинал':
    'Edit deleted, showing the game original',
  'QC модели': 'Model QC',
  'Вернуть авто-QC': 'Back to auto QC',
  'своя правка': 'custom edit',
  'авто-QC': 'auto QC',
  'Показана ваша правка': 'Showing your edit',
  'Показан исправленный авто-QC': 'Showing the corrected auto QC',
  'Сохранено': 'Saved',
  'Возвращён авто-QC': 'Auto QC restored',

  // ── Своя модель ───────────────────────────────────────────────────────
  'Своя модель убрана': 'Custom model removed',
  'Конвертация {}…': 'Converting {}…',
  'Как использовать модель?': 'How to use the model?',
  'Материалы модели:': 'Model materials:',
  'Материалов в модели не нашлось.': 'No materials found in the model.',
  'Со своими материалами и костями': 'With its own materials and bones',
  'Каждый материал модели получит свой слот текстуры, кости с игровыми именами оживут в анимациях, QC можно править. Для моделей, сделанных под это оружие':
    'Every material of the model gets its own texture slot, bones named like in the game animate, the QC is editable. For models made for this weapon',
  'Только форма — материалы оружия': 'Shape only — weapon materials',
  'Все материалы модели схлопнутся в материал оружия: одна текстура на всё, кости игровые. Для моделей с сайта и простых замен':
    'All materials collapse into the weapon material: one texture for everything, game bones. For downloaded models and simple swaps',
  'Загрузить': 'Load',
  'Своя модель: материалы её собственные':
    'Custom model: its own materials',
  'Своя модель: геометрия ваша, текстуры игровые':
    'Custom model: your geometry, game textures',

  // ── Материалы и текстуры ──────────────────────────────────────────────
  'У текстуры покадровая анимация': 'This texture is frame animated',
  'Своя картинка встанет одним кадром, и анимация пропадёт.':
    'A custom image becomes a single frame and the animation is lost.',
  'Всё равно заменить': 'Replace anyway',
  'Замена текстуры…': 'Replacing the texture…',
  'Своя картинка…': 'Custom image…',
  'Игровая текстура из списка…': 'Game texture from the list…',
  'Переименовать материал…': 'Rename the material…',
  'Разрешение своей картинки: {}': 'Custom image resolution: {}',
  'Разрешение своей картинки': 'Custom image resolution',
  'Больше — чётче вблизи, но тяжелее мод. У надписей крита в игре 256.':
    'Bigger is sharper up close but makes the mod heavier. Crit text in the game is 256.',
  'Разрешение {} возьмёт следующая картинка': 'The next image will use {}',
  'Вернуть текстуру игры': 'Bring back the game texture',
  'Текстура из эффектов игры': 'Texture from the game effects',
  'Такой материал уже есть в игре, поэтому мод работает в казуале.':
    'This material already exists in the game, so the mod works in casual.',
  'Заменить': 'Replace',
  'Новый путь материала': 'New material path',
  ' · покадровая анимация': ' · frame animation',
  'Выбрать': 'Pick',
  'главная текстура': 'main texture',
  'Карты материала: {}': 'Material maps: {}',
  'Карты материала сняты': 'Material maps cleared',

  // ── Превью ────────────────────────────────────────────────────────────
  'Загрузка стиля: {}…': 'Loading the style: {}…',
  'Загрузка модели…': 'Loading the model…',
  'Загрузка текстуры…': 'Loading the texture…',
  'Сборка сцены: {}…': 'Building the scene: {}…',
  // ── Звуки ──────────────────────────────────────────────────────────── //
  'Звуки': 'Sounds',
  'Событие': 'Event',
  'Название, предмет или файл': 'Name, item or file',
  'Своих звуков нет': 'No sounds of your own',
  'Своих файлов: {}': 'Your files: {}',
  'Частично': 'Partly',
  'общий для {}': 'shared by {}',
  'также у: {}': 'also at: {}',
  ' — возможно: ': ' — maybe: ',
  'Файлов другого формата осталось игровыми: {}':
    'Files of another format left as they are: {}',
  'Записей: {}': 'Entries: {}',
  'Показать ещё {}': 'Show {} more',
  '{} из {}': '{} of {}',
  'Раздел': 'Section',
  'Вариант': 'Variant',
  'Формат': 'Format',
  'Свои': 'Own',
  'Заменённые': 'Replaced',
  // Кто звучит — говорящие, которые не классы.
  'Диктор': 'Announcer',
  'Мисс Полинг': 'Miss Pauling',
  'Хэллоуин': 'Halloween',
  'Ап-Сап': 'Ap-Sap',
  'Прочие': 'Other',
  // Варианты записи.
  'Обычные': 'Regular',
  'Роботы MvM': 'MvM robots',
  'Читаю звуки игры…': 'Reading the game sounds…',
  'Читаю список…': 'Reading the list…',
  'Собираю эффект…': 'Assembling the effect…',
  'Мод заменяет {} — можно посмотреть в руках':
    'The mod replaces {} — you can see it in hand',
  'Ищу…': 'Searching…',
  'Под этими фильтрами ничего нет': 'Nothing matches these filters',
  ' — есть в разделе ': ' — found in ',
  'Раздел пуст: звуковые скрипты игры не прочитались':
    'The section is empty: the game sound scripts were not read',
  'Выстрел': 'Fire',
  'Крит': 'Crit',
  'Перезарядка': 'Reload',
  'Удар': 'Hit',
  'Достать': 'Draw',
  'Взрыв': 'Explosion',
  'Раскрутка': 'Spin-up',
  'Реплики': 'Voice',
  'Игрок': 'Player',
  'Мир': 'World',
  'Лечение': 'Healing',
  'Постройки': 'Buildings',
  'Хитсаунд': 'Hit sound',
  'Смерть': 'Death',
  'Боль': 'Pain',
  'Команды': 'Voice commands',
  'Автореплики': 'Auto responses',
  'Доминация': 'Domination',
  'Смех': 'Laughter',
  'Насмешки': 'Taunts',
  'Соревновательный': 'Competitive',
  'Ход матча': 'Match flow',
  'Контракты': 'Contracts',
  'Праздники': 'Holidays',
  'КПК': 'PDA',
  'Выбор класса': 'Class selection',
  'Урон': 'Damage',
  'Состояние': 'Status',
  'Интерфейс': 'Interface',
  'Музыка': 'Music',
  'Окружение': 'Ambience',
  'Шаги': 'Footsteps',
  'Физика': 'Physics',
  '{} и ещё {}': '{} and {} more',
  'Прослушать': 'Play',
  'Оригинал': 'Original',
  'Скачать': 'Save',
  'Сохранено: {}': 'Saved: {}',
  'Сохранено файлов: {}, рядом с {}': 'Files saved: {}, next to {}',
  'Файла этого звука в игре нет': 'The game has no file for this sound',
  'Не удалось сохранить: {}': 'Could not save: {}',
  'Свой файл': 'Own file',
  'Этот файл браузер проиграть не может': 'The browser cannot play this file',
  'Состояние модели': 'Model state',
  'Состояние · {}': 'State · {}',
  'Состояние модели: игра переключает его сама, здесь можно посмотреть каждое':
    'Model state: the game switches it by itself; here you can look at each one',
  'Собираю состояние…': 'Building the state…',
  'Такого состояния у модели нет': 'The model has no such state',
  // ── Праздничная версия (гирлянда поверх оружия) ──
  'Версия': 'Version',
  'Гирлянда, которую игра вешает на это оружие. Её правки уходят в мод отдельной моделью и не задевают другие оружия':
    'The lights the game hangs on this weapon. Edits go into the mod as a separate model and do not touch other weapons',
  'Обычная': 'Regular',
  'Праздничная': 'Festive',
  'Фестивайзер': 'Festivized',
  'Загрузка гирлянды…': 'Loading the lights…',
  'Висит как на стоковой модели — подгоните под свою': 'Placed as on the stock model — fit it to yours',
  'Не удалось показать гирлянду: {}': 'Could not show the lights: {}',
  'Гирлянду этой версии не удалось загрузить': 'Could not load the lights for this version',
  'У этого предмета такой версии нет': 'This item has no such version',
  'Подогнать гирлянду': 'Fit the lights',
  'Гнуть: тяните гирлянду мышью, колесо — радиус': 'Bend: drag the lights with the mouse, wheel changes the radius',
  'Гнуть': 'Bend',
  'Выпрямить: убрать все изгибы гирлянды': 'Straighten: remove all bends of the lights',
  'Выпрямить': 'Straighten',
  'Радиус': 'Radius',
  'Радиус захвата: всё внутри тянется следом. Колесо мыши в кадре — тоже':
    'Grab radius: everything inside follows. The mouse wheel in the frame does the same',
  'Изгиб без точки, радиуса или сдвига': 'A bend without a point, radius or offset',
  'Сдвинуть, повернуть и растянуть гирлянду под свою модель (G/R/S)':
    'Move, rotate and scale the lights to fit your model (G/R/S)',
  'Гирлянда: {}': 'Lights: {}',
  'Сначала включите праздничную версию': 'Turn on the festive version first',
  'Гирлянда не показана': 'The lights are not shown',
  'Части красят основное состояние модели — верните переключатель':
    'Parts paint the main state of the model — switch it back',
  'после взрыва': 'after the explosion',
  'разбитая': 'broken',
  'без части': 'without the part',
  'основной': 'main',
  'Базовый': 'Default',
  'Перекодирую звук…': 'Converting the sound…',
  'Не разобрать этот звук: {}': 'Cannot decode this sound: {}',
  'Игра ждёт здесь MP3, а перекодировать в MP3 браузер не умеет':
    'The game expects MP3 here, and the browser cannot encode MP3',
  'Готово: {} файлов в {}': 'Done: {} files in {}',
  'Такой записи в игре нет': 'There is no such entry in the game',
  'Такого файла у этой записи нет': 'This entry has no such file',
  'Не выбран звук': 'No sound selected',
  'Файл не подойдёт: {}': 'That file will not do: {}',
  'игра ждёт здесь {}, а это {} — звук просто не зазвучит':
    'the game expects {} here, and this is {} — it simply will not play',
  'Не выбрано ни одного своего звука': 'No sounds of your own were chosen',
  'Ничего не играет': 'Nothing is playing',
  '{} — свой файл': '{} — your file',
  'Играть': 'Play',
  'Перемотка': 'Seek',
  'Громкость': 'Volume',
  'Заменён': 'Replaced',
  'Собираем сцену…': 'Building the scene…',
  'Сборка вида от первого лица…': 'Building the first-person view…',
  'Извлечение граней неба…': 'Extracting the sky faces…',
  'Не удалось показать модель: {}': 'Could not show the model: {}',
  'Не удалось показать сцену: {}': 'Could not show the scene: {}',
  'Не удалось загрузить: {}': 'Could not load: {}',
  'В игре синий вариант этой модели не отличается от красного':
    'In the game the BLU variant of this model is the same as RED',
  'Материалы стиля: остальные наследуют базовую текстуру.':
    'Materials of this style: the rest inherit the base texture.',
  'Стиль пока целиком наследует базу. Добавьте материал, чтобы дать ему свою текстуру.':
    'For now the style inherits the base entirely. Add a material to give it a texture of its own.',
  'Какой материал меняет этот стиль': 'Which material this style changes',
  'Положите картинку в кадр — модели у этого режима нет':
    'Drop an image into the frame — this mode has no model',
  'Картинка ляжет билбордом над персонажем':
    'The image is shown as a billboard above the character',
  'Картинка ляжет на персонажа — так эффект выглядит в игре':
    'The image goes onto the character — that is how the effect looks in the game',
  'У этого неба граней в игре не нашлось':
    'No faces for this sky were found in the game',
  'Найдено граней: {} из 6': 'Faces found: {} of 6',
  'Анимации интерфейса': 'Interface animations',
  'Плавное появление панелей, перелёт камеры, разъезд половин стола. Без них всё переключается мгновенно':
    'Panels fading in, the camera flying, the two halves sliding apart. Without them everything switches instantly',
  'Панорама 360°': '360° panorama',
  'Загрузите панораму 360° или грани неба':
    'Load a 360° panorama or the sky faces',
  'Перетащите фото 360° (2:1) — оно разрежется на все шесть граней':
    'Drop a 360° photo (2:1) — it will be split into all six faces',

  // ── Части модели ──────────────────────────────────────────────────────
  'Части': 'Parts',
  'Картинка': 'Image',
  'Кисть': 'Brush',
  'Пипетка': 'Eyedropper',
  'Взять цвет с модели или с текстуры':
    'Take a color from the model or from the texture',
  'Зажми на модели или на текстуре — цвет виден под курсором, а берётся там, где отпустишь':
    'Hold the button on the model or on the texture — the color shows under '
    + 'the cursor and is taken where you release it',
  'Взят цвет {}': 'Picked the color {}',
  'Пипеткой щёлкай по модели или по текстуре слева, а не по списку':
    'Use the eyedropper on the model or on the texture at the left, '
    + 'not on the list',
  'Возьми кисть справа — щелчок по части покрасит её':
    'Take the brush on the right — a click on a part will paint it',
  'Цвет выбран — возьми кисть, чтобы им красить':
    'The color is chosen — take the brush to paint with it',
  'Возьми значок справа: кисть красит, ножницы дробят кусок. Ctrl+Z отменяет, Ctrl+Y возвращает':
    'Take an icon on the right: the brush paints, the scissors cut a piece '
    + 'finer. Ctrl+Z undoes, Ctrl+Y redoes',
  'Щёлкай по частям — покрасятся. Alt при щелчке берёт цвет с модели или с текстуры':
    'Click the parts to paint them. Alt-click takes a color from the model or '
    + 'from the texture',
  'Нарезка': 'Cutting',
  'Окантовка': 'Outline',
  'Градиент': 'Gradient',
  'Сила': 'Strength',
  'Точный цвет': 'Exact color',
  'Окантовка пойдёт по краям тех частей, которые покрасишь дальше':
    'The outline will follow the parts you paint from now on',
  'Цвет ложится ровно как в палитре; фактура остаётся за счёт теней':
    'The color lands exactly as in the palette; the texture survives '
    + 'through its own shadows',
  'Цвет смешивается с оригиналом — так деталь выглядит естественнее':
    'The color blends with the original — that way the part looks more natural',
  'Объединить': 'Merge',
  // ── Ножницы: выделение и «Отделить» ──────────────────────────────────
  'Деталь': 'Piece',
  'Остров': 'Island',
  'Острота рёбер': 'Edge sharpness',
  'Размер кисти': 'Brush size',
  'Стирать': 'Erase',
  'Отделить': 'Separate',
  'Щелчок берёт гладкую поверхность до острых рёбер': 'A click takes a smooth surface up to its sharp edges',
  'Веди по модели — выделяется всё под кистью': 'Drag over the model — everything under the brush is selected',
  'Щелчок берёт остров развёртки целиком': 'A click takes a whole UV island',
  'Меньше — деталь дробится на грани, больше — берётся крупнее': 'Lower splits a detail into faces, higher takes bigger pieces',
  'Выделенное — в отдельную часть (Enter)': 'Make the selection a separate part (Enter)',
  'Снять выделение (Esc)': 'Clear the selection (Esc)',
  'Разрезать все куски по островам развёртки разом': 'Split every piece along its UV islands at once',
  'Часть возвращена на место': 'The part is back where it was',
  'Сперва выдели на модели, что отделить': 'First select on the model what to separate',
  'Отделяю…': 'Separating…',
  'Отделено. Зеркальная половина отделилась вместе: у неё те же пиксели': 'Separated. The mirrored half came along: it uses the same pixels',
  'Отделено в новую часть. Вернуть — «−» на её чипе или Ctrl+Z': 'Separated into a new part. To undo — “−” on its chip or Ctrl+Z',
  'Выделено треугольников: {}. «Отделить» или Enter — в отдельную часть': 'Triangles selected: {}. “Separate” or Enter makes them a part',
  'Щёлкай по модели: берётся гладкая поверхность до острых рёбер. Повторный щелчок снимает': 'Click the model: a smooth surface up to its sharp edges is taken. Click again to drop it',
  'Веди по модели с зажатой кнопкой — выделяется всё под кистью. Мимо модели — крутит камеру': 'Drag over the model with the button held — everything under the brush is selected. Off the model it orbits the camera',
  'Щёлкай по модели: берётся остров развёртки целиком': 'Click the model: a whole UV island is taken',
  'Выдели на модели, что отрезать, и нажми «Отделить». Щелчок по чипу берёт часть целиком — так части сводят в одну': 'Select on the model what to cut off and press “Separate”. Clicking a chip takes the whole part — that is how parts are merged',
  'Ничего не выделено': 'Nothing is selected',
  'Выделено: {}': 'Selected: {}',
  'Нарезать по островам': 'Split by UV islands',
  // ── Посадка картинки: отражение, копия, сетка ────────────────────────
  'Сетка': 'Mesh',
  'Показать сетку треугольников детали вместо её контура — на мелкой детали видно, куда именно ляжет картинка': 'Show the part’s triangle mesh instead of its outline — on a small part you see exactly where the picture lands',
  'Тяни мышью · размер — за квадратики, за край дальше противоположного — отражение · поворот — за маркер или стрелками · колесо — ближе': 'Drag to move · size — by the squares, past the opposite edge — mirror · rotate — by the handle or arrow keys · wheel — closer',
  'Скопировать картинку с посадкой (Ctrl+C)': 'Copy the picture with its placement (Ctrl+C)',
  'Вставить скопированную картинку поверх (Ctrl+V)': 'Paste the copied picture on top (Ctrl+V)',
  'Минус — отражение по ширине': 'Minus mirrors horizontally',
  'Минус — отражение по высоте': 'Minus mirrors vertically',
  'Вставляю…': 'Pasting…',
  'Картинка скопирована. На другую часть — наведи на неё на модели и нажми Ctrl+V': 'Picture copied. For another part — hover it on the model and press Ctrl+V',
  'Тяни за заголовок — двигать, за уголок справа снизу — менять размер. Двойной щелчок — вернуть на место': 'Drag the title to move, the bottom-right corner to resize. Double-click puts it back',
  'Картинка вставлена — поправить посадку можно в «…»': 'Picture pasted — adjust its placement with “…”',
  'Не удалось перейти к материалу выделения — попробуй ещё раз': 'Could not switch to the selection’s material — try again',
  'Обводить': 'Outline',
  'Толщина': 'Width',
  'Отменить': 'Undo',
  'Случайно': 'Random',
  'Убрать всё': 'Clear all',
  'Свой цвет': 'Custom color',
  'Красить переходом из первого цвета во второй':
    'Paint with a gradient from the first color to the second',
  'Второй цвет градиента': 'Second gradient color',
  'Направление перехода — потяни или стрелками':
    'Gradient direction — drag it or use the arrows',
  'Направление перехода: {}°': 'Gradient direction: {}°',
  'Щёлкать по кускам модели, чтобы дробить их мельче':
    'Click parts of the model to cut them finer',
  'Обвести края покрашенных частей': 'Outline the edges of painted parts',
  'Цвет окантовки': 'Outline color',
  'Эта модель — один цельный кусок, делить нечего':
    'This model is a single solid piece, there is nothing to split',
  'Щёлкай по частям модели — покрасятся в этот цвет':
    'Click the parts of the model to paint them this color',
  'Положить картинку на часть': 'Place an image on the part',
  'Красить части выбранным цветом': 'Paint parts with the chosen color',
  'Щёлкай по частям модели или тащи на них картинку — она ляжет на кусок':
    'Click the parts of the model or drag an image onto them — it will land '
    + 'on that piece',
  'Чем красить: цвет или переход': 'What to paint with: a color or a gradient',
  'Цвет кисти': 'Brush color',
  'У этой части своя картинка — цвет лёг под неё':
    'This part has its own image — the color went underneath it',
  'Начало перехода: за ним первый цвет чистый':
    'Where the blend starts: before it the first color is pure',
  'Середина: где цвета смешаны поровну':
    'The midpoint: where the colors are mixed evenly',
  'Конец перехода: за ним второй цвет чистый':
    'Where the blend ends: past it the second color is pure',
  'Свернуть палитру': 'Collapse the palette',
  'Развернуть палитру': 'Expand the palette',
  'Часть': 'Part',
  'Часть ': 'Part ',
  ' развёртки': ' of the UV map',
  'часть {} · развёртка {} тр.': 'part {} · UV {} tri',
  'развёртки': 'of the UV map',
  'Делит развёртку с другими: в игре они покрасятся вместе, разными их сделать нельзя':
    'Shares the UV map with others: in the game they are painted together and cannot be made different',
  'Прирастить обратно': 'Grow it back',
  'Картинки части: посадка, замена, ещё одна':
    'Images on the part: placement, replace, one more',
  'Такой картинки на части нет': 'There is no such image on the part',
  'Заменить…': 'Replace…',
  '+ Добавить': '+ Add',
  'Другой файл на место этой картинки, посадка останется':
    'Another file in place of this image; the placement stays',
  'Снять эту картинку с части': 'Take this image off the part',
  'Ещё одна картинка поверх': 'One more image on top',
  'Убираю…': 'Removing…',
  'Переставляю…': 'Reordering…',
  'поверх': 'on top',
  'внизу': 'bottom',
  'Вернуть этой части игровую текстуру':
    'Bring back the game texture for this part',
  'У этого куска один остров развёртки — резать нечего':
    'This piece has a single UV island — there is nothing to cut',
  'Режу…': 'Cutting…',
  'Отрезано {} остров из {}': 'Cut off {} island of {}',
  'Отрезано {} острова из {}': 'Cut off {} islands of {}',
  'Отрезано {} островов из {}': 'Cut off {} islands of {}',
  '. Вернуть — щелчок по нему же или «−» на его чипе':
    '. To bring it back click it again, or press “−” on its chip',
  'Наложение на часть…': 'Placing on the part…',
  'Эта часть делит развёртку с соседними — они покрасились вместе':
    'This part shares the UV map with its neighbours — they were painted together',
  'Не удалось: {}': 'Failed: {}',
  'Перерезаю модель…': 'Re-cutting the model…',
  'Частей:': 'Parts:',
  'Случайная раскраска — щёлкай по частям, чтобы поправить':
    'Random coloring — click the parts to fix it up',
  'Отменено': 'Undone',
  'Возвращено': 'Redone',
  'Градиент: щёлкай по частям — переход из первого цвета. Полоса задаёт края и середину перелива, ручка — направление':
    'Gradient: click the parts to fill them from the first color. The bar sets '
    + 'the edges and the midpoint of the blend, the handle sets the direction',
  'Перекладываю…': 'Re-placing…',

  // ── Посадка картинки на часть ─────────────────────────────────────────
  'Вписать': 'Fit',
  'Целиком': 'Whole',
  'Заполнить': 'Fill',
  'Растянуть': 'Stretch',
  'Ширина': 'Width',
  'Высота': 'Height',
  'Приблизить': 'Zoom',
  'Без игровой': 'No game texture',
  'Размер, %': 'Size, %',
  'Посадка картинки': 'Image placement',
  'Слои': 'Layers',
  'Верхний лежит поверх остальных. Тяни строку, чтобы переставить':
    'The top one lies over the rest. Drag a row to reorder',
  'Показ': 'View',
  'Приблизить холст к куску: класть картинку, глядя на всю текстуру, — целиться в спичку с другого конца комнаты':
    'Zoom the canvas to the piece: placing an image while looking at the whole texture is like aiming at a match from across the room',
  'Спрятать игровую текстуру: на пёстрой не видно границ своей картинки':
    'Hide the game texture: on a busy one the edges of your image are hard to see',
  'Целиком в место части, с сохранением пропорций':
    'Whole into the part area, proportions kept',
  'Заполнить место части, края уйдут под маску':
    'Fill the part area, the edges go under the mask',
  'Растянуть по месту части, пропорции не сохраняются':
    'Stretch over the part area, proportions are not kept',
  'Угол': 'Angle',
  'Сдвиг, % места': 'Offset, % of the area',
  'Вправо': 'Right',
  'Вниз': 'Down',
  'Сбросить посадку': 'Reset placement',
  'Вернуть посадку к исходной: целиком, без поворота и сдвига':
    'Back to the initial placement: whole, no rotation, no offset',
  'Отменить правку (Ctrl+Z)': 'Undo (Ctrl+Z)',
  'Вернуть правку (Ctrl+Y)': 'Redo (Ctrl+Y)',

  // ── Инструменты ───────────────────────────────────────────────────────
  'Загрузка {}…': 'Loading {}…',
  'Не удалось открыть: {}': 'Could not open: {}',
  'Куда сохранить PCF': 'Where to save the PCF',
  'Сохранено: {} ({} Б)': 'Saved: {} ({} B)',
  'Сбор справочника…': 'Collecting the reference…',
  'Справочник сохранён: {}': 'Reference saved: {}',
  'Построение UV-шаблона…': 'Building the UV template…',
  'UV-шаблон не построен': 'The UV template was not built',
  'UV-шаблон': 'UV template',
  'UV-шаблон {}': 'UV template {}',
  'UV-шаблон: {}': 'UV template: {}',
  'UV-шаблоны: {} шт.': 'UV templates: {}',
  'Извлечение модели…': 'Extracting the model…',
  'Модель не извлечена': 'The model was not extracted',
  'Что сохранить в папку экспорта': 'What to save into the export folder',
  'Извлечение отменено': 'Extraction cancelled',
  'Какие текстуры извлечь': 'Which textures to extract',
  'Извлечь': 'Extract',
  'Извлечение текстуры…': 'Extracting the texture…',
  'В папке экспорта нет собранных модов':
    'There are no built mods in the export folder',
  'Какие моды объединить': 'Which mods to merge',
  'Далее': 'Next',
  'Имя выходного файла': 'Output file name',
  'Моды трогают одно оружие': 'The mods touch the same weapon',
  '{}\nОдин перекроет другой. Продолжить?': '{}\nOne will override the other. Continue?',
  'Объединение…': 'Merging…',
  'Не получилось': 'It did not work out',

  // ── Редактор частиц ───────────────────────────────────────────────────
  'Обычный': 'Simple',
  'Эксперт': 'Expert',
  'Правая кнопка — действия над системой, модулем и параметром':
    'Right click — actions on the system, the module and the parameter',
  'Поиск параметра': 'Find a parameter',
  'Точка': 'Point',
  'Позиция': 'Position',
  'Углы': 'Angles',
  'углы задают оси скорости и плоскость спрайтов':
    'the angles set the velocity axes and the sprite plane',
  'Движение': 'Motion',
  'Неподвижно': 'Still',
  'Покачивание вверх-вниз': 'Bobbing up and down',
  'Шаг вбок с подскоком': 'A hop to the side',
  'По кругу': 'In a circle',
  'Разворот на месте': 'Turning in place',
  'Амплитуда': 'Amplitude',
  'Период, с': 'Period, s',
  'Сбросить': 'Reset',
  'Модель…': 'Model…',
  'В мире': 'In the world',
  'На модели': 'On the model',
  'Точка крепления': 'Attachment point',
  'Анимация': 'Animation',
  'Заново': 'Restart',
  'Пауза': 'Pause',
  'Продолжить': 'Resume',
  'Повтор': 'Loop',
  'Повторить': 'Redo',
  'Точки': 'Points',
  'Вернуть': 'Restore',
  'Свернуть': 'Collapse',
  'Развернуть': 'Expand',
  '{} · дочерних: {}': '{} · children: {}',
  ' систем, корней ': ' systems, roots ',
  'В этом файле систем нет.': 'This file has no systems.',
  'Ничего не найдено.': 'Nothing found.',
  'Источник': 'Source',
  'Все эффекты игры': 'All game effects',
  'Без предмета': 'No item',
  'Попадания и взрывы': 'Impacts and explosions',
  'Анюжуалы': 'Unusuals',
  'Режимы и правила': 'Modes and rules',
  'Карты и окружение': 'Maps and ambience',
  'Индекс эффектов ещё строится — пока ищем только по именам из игры.':
    'The effect index is still being built — searching game names only for now.',
  'Индекс эффектов ещё строится — попробуйте через несколько секунд':
    'The effect index is still being built — try again in a few seconds',
  'В файле нет такой системы': 'The file has no such system',
  'эффект': 'effect',
  'эффекта': 'effects',
  'эффектов': 'effects',
  'Килстрик': 'Killstreak',
  'Заново (R)': 'Restart (R)',
  'Нет в игре': 'Not in the game',
  'Изменена относительно игры': 'Changed from the game version',
  ' · изменена относительно игры': ' · changed from the game',
  ' · нет в игре': ' · not in the game',
  'Вернуть как в игре': 'Revert to game version',
  'Вернуть систему как в игре?': 'Revert the system to the game version?',
  'Все правки этой системы — параметры, модули, дочерние — будут заменены игровыми.':
    'Every edit of this system — parameters, modules, children — will be replaced with the game ones.',
  'В игре такой системы нет — возвращать не к чему':
    'The game has no such system — nothing to revert to',
  'не удалось вернуть {}': 'could not revert {}',
  'Система возвращена к игровой': 'The system is back to the game version',
  'Вернуть значение игры': 'Revert to the game value',
  'убран: ': 'removed: ',
  'нет в игре': 'not in the game',
  'Пауза (пробел)': 'Pause (Space)',
  'Скорость времени (S)': 'Time speed (S)',
  'системы': 'systems',
  'систем': 'systems',
  'система': 'system',
  'не в превью': 'not in the preview',
  'эффекту нужны: {}': 'the effect needs: {}',
  'Эту точку эффект использует': 'The effect uses this point',
  'В кэше нет разобранных моделей — откройте модель на вкладке оружия или шапок, и она появится здесь':
    'The cache has no decompiled models — open a model on the weapons or cosmetics tab and it will show up here',
  'Показать': 'Show',
  'Сборка меша модели…': 'Building the model mesh…',
  '— не выбрана —': '— none —',
  'Правка отменена': 'Edit undone',
  'Правка возвращена': 'Edit redone',
  'В этой системе нет модуля для этого параметра, а создавать его нельзя: лишний эмиттер задваивает залп.':
    'This system has no module for that parameter, and creating one is not allowed: an extra emitter doubles the burst.',
  'не получилось': 'it did not work out',
  'В какую группу': 'Into which group',
  'operators — что делает с частицей по ходу жизни':
    'operators — what happens to the particle over its life',
  'initializers — каким рождается': 'initializers — how it is born',
  'renderers — чем рисуется': 'renderers — how it is drawn',
  'emitters — как выпускаются': 'emitters — how they are released',
  'forces — что на неё давит': 'forces — what pushes it',
  'constraints — что ограничивает': 'constraints — what limits it',
  'Дальше': 'Next',
  'Какой модуль': 'Which module',
  'Сверху — ходовые, ниже всё, что встречается в эффектах игры.':
    'The common ones are on top, below is everything found in the game effects.',
  'Добавить': 'Add',
  'Удалить модуль?': 'Delete the module?',
  'Удалить': 'Delete',
  'Раскройте модуль в экспертном режиме — параметр добавляется в него':
    'Open the module in expert mode — the parameter is added to it',
  'Все известные параметры уже заданы': 'Every known parameter is already set',
  'Поиск': 'Search',
  'Игроки': 'Players',
  'корень': 'root',
  'Классы': 'Classes',
  'Из кэша': 'From cache',
  'Ничего не найдено': 'Nothing found',
  'Какой класс': 'Which class',
  'У этой шапки своя модель на каждый класс.': 'This cosmetic has its own model per class.',
  'Модель для точек': 'Model for control points',
  'Разбор модели…': 'Decompiling the model…',
  'Для «{}» модель не найти': 'No model can be found for “{}”',
  'QC после разбора не найден': 'No QC after decompiling',
  'У шапки нужен путь модели': 'A cosmetic needs its model path',
  'У «{}» нет модели': '“{}” has no model',
  'Косметика': 'Cosmetics',
  'Руки': 'Hands',
  'Фон': 'Backdrop',
  'Тёмный, серый или светлый фон кадра: полупрозрачные слои эффекта видны только на светлом':
    'Dark, grey or light backdrop: translucent layers of an effect only show on a light one',
  'Какой параметр': 'Which parameter',
  'Свои параметры у этого модуля уже все заданы. Остались общие для любого модуля: плавное включение и выключение по времени жизни системы.':
    'This module already has all of its own parameters. What is left is common to every module: fading the operator in and out over the system lifetime.',
  'Значение подставится такое, как в эффектах игры.':
    'The value is taken from the game effects.',
  'Скопирован параметр «{}»': 'Copied the “{}” parameter',
  'Скопирован модуль': 'Copied the module',
  'Скопирована группа «{}»': 'Copied the “{}” group',
  'Скопирована вся система эффекта': 'Copied the whole effect system',
  'Скопируйте набор параметров': 'Copy the parameter set',
  'Буфер обмена недоступен — выделите и скопируйте.':
    'The clipboard is not available — select and copy by hand.',
  'Вставьте набор параметров': 'Paste the parameter set',
  'JSON с ключом tf2sgParticleParams': 'JSON with a tf2sgParticleParams key',
  'В буфере не JSON: {}': 'The clipboard does not hold JSON: {}',
  'В JSON нет раздела tf2sgParticleParams':
    'The JSON has no tf2sgParticleParams section',
  'Как вставить': 'How to paste',
  'Поверх — совпадающие параметры заменить':
    'Over — replace the matching parameters',
  'Без замены — дописать только недостающее':
    'Without replacing — add only what is missing',
  'Полная замена — снести модули системы':
    'Full replacement — wipe the system modules',
  'Вставить': 'Paste',
  'Вставлено, но часть пропущена: {}': 'Pasted, but some of it was skipped: {}',
  'Имя копии': 'Name of the copy',
  'Новое имя системы': 'New system name',
  'Дочерние системы': 'Child systems',
  'Пока ни одной.': 'None yet.',
  'Подцепить существующую…': 'Attach an existing one…',
  'Отцепить…': 'Detach…',
  'Какую систему подцепить': 'Which system to attach',
  'Подцепить': 'Attach',
  'Какую отцепить': 'Which one to detach',
  'Отцепить': 'Detach',
  'Слой добавлен — задайте ему параметры и текстуру':
    'Layer added — give it parameters and a texture',
  'Показать родные цвета текстур?': 'Show the native texture colors?',
  'У этой системы и её дочерних будут удалены модули цвета, а базовый цвет станет белым.':
    'Color modules will be removed from this system and its children, and the base color becomes white.',
  'Убрать подкраску': 'Remove the tint',
  'Удалено модулей цвета: {}': 'Color modules removed: {}',
  'Модулей цвета не было — текстуры уже в родных цветах':
    'There were no color modules — the textures already show their native colors',
  'Удалить систему?': 'Delete the system?',
  'Копировать все параметры системы': 'Copy every parameter of the system',
  'Вставить параметры': 'Paste parameters',
  'Добавить слой со своей текстурой…': 'Add a layer with a custom texture…',
  'Переименовать систему…': 'Rename the system…',
  'Дублировать систему…': 'Duplicate the system…',
  'Добавить дочернюю…': 'Add a child…',
  'Удалить систему': 'Delete the system',
  'Цвета текстуры (снять подкраску)': 'Texture colors (remove the tint)',
  'Отцепить дочернюю': 'Detach the child',
  'Копировать группу «{}»': 'Copy the “{}” group',
  'Добавить модуль…': 'Add a module…',
  'Копировать параметр «{}»': 'Copy the “{}” parameter',
  'Добавить параметр…': 'Add a parameter…',
  'Удалить параметр (вернуть умолчание)':
    'Delete the parameter (back to the default)',
  'Копировать этот модуль': 'Copy this module',
  'Удалить модуль': 'Delete the module',
  'Проверка эффекта…': 'Checking the effect…',
  'Проверка перед сборкой': 'Check before building',
  '…и ещё {}': '…and {} more',
  'Исправить ({}) и собрать': 'Fix ({}) and build',
  'Собрать как есть': 'Build as is',
  'Имя файла мода': 'Mod file name',
  'Сборка VPK…': 'Building the VPK…',
  'Собрано, но PCF на {} Б больше оригинала — в казуале не загрузится':
    'Built, but the PCF is {} B larger than the original — casual will not load it',

  // ── Сообщения Python: ошибки сеанса ───────────────────────────────────
  'Сначала выберите предмет': 'Select an item first',
  'Сначала выберите шапку': 'Select a cosmetic first',
  'Сначала извлеките модель': 'Extract the model first',
  'Модель ещё не загружена': 'The model is not loaded yet',
  'Файл не найден': 'File not found',
  'Файл модели не найден': 'Model file not found',
  'Не найдены:': 'Not found:',
  'VPK-файл не найден': 'VPK file not found',
  '«{}» в библиотеке нет': 'There is no “{}” in the library',
  'Сборка уже идёт': 'A build is already running',
  'Крутить гифки на модели': 'Play GIFs on the model',
  'Гифка, положенная на часть модели, крутится и в 3D. Каждый мазок пересчитывает кадры (секунды) и держит их на видеокарте (до сотен МБ)':
    'A GIF placed on a model part also plays in 3D. Every stroke recomputes the frames (seconds) and keeps them on the GPU (up to hundreds of MB)',
  'Анимация частей {}/{}': 'Part animation {}/{}',
  'Не удалось собрать анимацию частей: {}': 'Could not assemble the part animation: {}',
  'Проверка уже идёт': 'A check is already running',
  'Извлечение уже идёт': 'An extraction is already running',
  'Объединение уже идёт': 'A merge is already running',
  'Экспорт UV уже идёт': 'A UV export is already running',
  'Не загружено ни одной своей текстуры': 'No custom texture is loaded',
  'Вид от первого лица есть только у оружия':
    'The first-person view exists only for weapons',
  'Для режима «{}» 3D-модели нет': 'Mode “{}” has no 3D model',
  'Для режима «{}» модели нет': 'Mode “{}” has no model',
  'Для режима «{}» текстуры не найти': 'No texture can be found for mode “{}”',
  'Для этого режима модели нет': 'This mode has no model',
  'Для этого режима оригинальной текстуры нет':
    'This mode has no original texture',
  'Для этого режима редактор VMT недоступен':
    'The VMT editor is not available for this mode',
  'SMD не сконвертировался': 'The SMD did not convert',
  'QC правится только у своей готовой модели':
    'QC can be edited only for a finished custom model',
  'QC ещё не извлечён из игры — дождитесь загрузки модели':
    'The QC has not been extracted from the game yet — wait for the model to load',
  'Сохранять нечего: правок нет': 'Nothing to save: there are no edits',
  'Сохранённых правок у этого предмета нет':
    'This item has no saved edits',
  'В стиль можно добавить только материал модели':
    'Only a material of the model can be added to a style',
  'У этого материала нет геометрии': 'This material has no geometry',
  'Отменять нечего': 'There is nothing to undo',
  'Возвращать нечего': 'There is nothing to redo',
  'На этой части нет картинки': 'This part has no image',
  'У этой части нет развёртки': 'This part has no UV map',
  'Такой части нет': 'There is no such part',
  'Оригинальный VMT для «{}» не найден':
    'The original VMT for “{}” was not found',
  'Выберите хотя бы два мода': 'Select at least two mods',
  'Задайте имя выходного файла': 'Set the output file name',
  'Папка Team Fortress 2 не задана в настройках':
    'The Team Fortress 2 folder is not set in the settings',
  'Не удалось разобрать папку игры: {}': 'Could not read the game folder: {}',
  'В папке игры не найден tf2_misc_dir.vpk':
    'tf2_misc_dir.vpk was not found in the game folder',
  'не открыть VPK текстур: {}': 'could not open the textures VPK: {}',
  'PCF не загружен': 'No PCF is loaded',
  'PCF {} не разобран: {}': 'PCF {} was not parsed: {}',
  'неизвестный параметр: {}': 'unknown parameter: {}',
  'система не найдена: {}': 'system not found: {}',
  'модуль не найден': 'module not found',
  'параметра нет: {}': 'no such parameter: {}',
  'в этой системе нет модуля для этого параметра':
    'this system has no module for that parameter',
  'в этой системе нужного модуля нет': 'this system has no such module',
  'в группе {} нет модулей': 'group {} has no modules',
  'дальше некуда': 'nowhere further to go',
  'не удалось восстановить состояние': 'could not restore the state',
  'не удалось создать модуль {}': 'could not create module {}',
  'не удалось добавить {}': 'could not add {}',
  'не удалось удалить {}': 'could not delete {}',
  'не удалось удалить модуль': 'could not delete the module',
  'не удалось удалить систему': 'could not delete the system',
  'не удалось добавить слой': 'could not add the layer',
  'не удалось записать {}': 'could not write {}',
  'не удалось отцепить': 'could not detach it',
  'не подцепить: система не найдена или вышел бы цикл':
    'cannot attach: the system was not found, or it would make a loop',
  'не удалось дублировать — возможно, имя занято':
    'could not duplicate — the name may be taken',
  'не удалось переименовать — возможно, имя занято':
    'could not rename — the name may be taken',
  'не удалось переименовать — возможно, путь занят':
    'could not rename — the path may be taken',
  'вставить не удалось': 'pasting failed',
  'у этой модели нет reference-SMD': 'this model has no reference SMD',
  'не удалось собрать меш модели': 'could not build the model mesh',
  'меш модели для точек не построен: {}':
    'the model mesh for the points was not built: {}',
  'текстуры модели не найдены: {}': 'model textures not found: {}',
  'текстура {}: {}': 'texture {}: {}',
  'не удалось применить текстуру (см. журнал)':
    'could not apply the texture (see the log)',
  'у этого материала нет своей текстуры':
    'this material has no custom texture',
  'не удалось заменить материал': 'could not replace the material',
  'сборка VPK частиц не удалась: {}': 'building the particles VPK failed: {}',
  'не прочитать правку: {}': 'could not read the edit: {}',

  // ── Обновление приложения ─────────────────────────────────────────────
  'Проверить обновления': 'Check for updates',
  'проверяю…': 'checking…',
  'считаю…': 'counting…',
  'Установлена последняя версия.': 'You have the latest version.',
  'Не удалось проверить обновления.': 'Could not check for updates.',
  'Не удалось проверить обновления — нет связи с GitHub.':
    'Could not check for updates — no connection to GitHub.',
  'Доступна версия': 'Version available',
  'Нажмите «Обновить» — приложение закроется и вернётся уже новым.':
    'Press Update — the app will close and come back updated.',
  'Скачайте её со страницы релиза.': 'Download it from the release page.',
  'Обновить': 'Update',
  'Обновить до': 'Update to',
  'Открыть страницу релиза': 'Open the release page',
  'Приложение закроется, установщик заменит его на новую версию и запустит заново. Ваши работы, моды и настройки не тронутся — они хранятся отдельно от папки установки.':
    'The app will close, the installer will replace it with the new version and start it again. Your works, mods and settings are untouched — they live outside the installation folder.',
  'Скачиваю установщик…': 'Downloading the installer…',
  'Установщик запущен, приложение закрывается…':
    'Installer started, the app is closing…',
  'Обновление не установлено': 'The update was not installed',
  'Обновление не установлено: {}': 'the update was not installed: {}',
  'нечего устанавливать': 'nothing to install',

  // ── Журнал ────────────────────────────────────────────────────────────
  // «Журнал» и «Свернуть» уже есть выше — второй раз их писать нельзя:
  // TypeScript ловит это как ошибку, а без него молча побеждал бы последний.
  'Во всё окно': 'Full width',
  'Копировать': 'Copy',
  'Папка с логом': 'Log folder',
  'Потянуть за край': 'Drag the edge',
  'Поиск по журналу': 'Search the log',
  'Обмен': 'Calls',
  'Ошибки': 'Errors',
  'Предупреждения': 'Warnings',
  'Инфо': 'Info',
  'Отладка': 'Debug',
  'Пропущено записей:': 'Entries dropped:',
  '(журнал не успевали читать; всё есть в файле)':
    '(the log was not read in time; the file has everything)',
  'только Windows': 'Windows only',
  'не открыть папку журнала: {}': 'could not open the log folder: {}',

  // Записи логгера Python переводятся тем же способом, что и остальные
  // подписи, — на границе показа. Начали с ошибок, где человеку сказано, что
  // делать: их он читает и по ним действует. Диагностика уровня INFO/DEBUG
  // остаётся русской намеренно — её читает автор по присланному файлу.
  'items_game.txt не найден в {}': 'items_game.txt not found in {}',
  "Секция 'items' не найдена в items_game.txt":
    "the 'items' section was not found in items_game.txt",
  'Библиотека vpk не установлена. Установите через: pip install vpk':
    'the vpk library is not installed. Install it with: pip install vpk',
  'Модель не найдена для {}. Проверенные пути: {}':
    'no model found for {}. Paths tried: {}',

  // ── Диалог «не получилось» ────────────────────────────────────────────
  // Заголовок и объяснение приходят от Python уже на нужном языке
  // (error_classifier), здесь только подписи самого окна.
  'Технические детали': 'Technical details',
  'Открыть журнал': 'Open the log',

  // ── Редактор VMT: справочник и готовые эффекты ─────────────────────────
  'Готовые эффекты ▾': 'Presets ▾',
  'Справочник': 'Reference',
  'Найти параметр': 'Find a parameter',
  'Наведите на параметр — подсказка · Ctrl+S — сохранить': 'Hover a parameter for help · Ctrl+S to save',
  'Заменить весь материал': 'Replace the whole material',
  'Текущий VMT заменится этим шаблоном.': 'The current VMT will be replaced with this template.',
  'Ничего не нашлось': 'Nothing found',
  'Уже есть в материале — курсор на нём': 'Already in the material, the cursor is on it',

  // ── Сборка: краска игры по альфе ───────────────────────────────────────
  'Игра перекрасит предмет в {}': 'The game will paint the item {}',
  'Этот предмет игра красит там, где у текстуры белый альфа-канал. У вашей картинки альфы нет, поэтому в игре покрасится весь предмет.': "The game paints this item where the texture's alpha channel is white. Your image has no alpha, so the whole item will be painted in game.",
  'Как на картинке': 'As in the image',
  'Игра не будет его перекрашивать — как в превью': "The game won't paint it, just like the preview",
  'Покраска как в игре': 'Paint like the game',
  'Убрать покраску из VMT': 'Remove paint from the VMT',
  'То же, но параметры покраски удаляются из материала': 'Same result, but the paint parameters are removed from the material',
  'Цвет ляжет только туда, где его кладёт игра у оригинала': 'Color goes only where the game puts it on the original',
  'Покрасится весь предмет': 'The whole item gets painted',
  'Собрать': 'Build',

  // ── Шапка на модели ───────────────────────────────────────────────────
  'Основное': 'Primary',
  'Вспомогательное': 'Secondary',
  'Сапёр': 'Sapper',
  'Ближний бой': 'Melee',
  'Сборка сцены…': 'Building the scene…',
  'Посмотрите шапку прямо на персонаже. Под кадром можно выбрать класс и оружие в руках.': 'See the hat right on the character. Below the view you can pick the class and the weapon in hand.',
  'На модели показывается только косметика': 'Only cosmetics can be shown on the model',
  'Не удалось понять, какой класс носит эту шапку': "Couldn't tell which class wears this hat",

  // ── Обучение (tour.js) ────────────────────────────────────────────────
  'Пройти обучение заново':
    'Replay the tutorial',
  'Пропустить обучение':
    'Skip tutorial',
  'Продолжу, когда сделаете':
    'I\'ll continue once you do it',
  'Добро пожаловать':
    'Welcome',
  'Покажу, как сделать скин: выбрать оружие, положить на него свою картинку и собрать мод. Это займёт минуту.':
    'I\'ll show you how to make a skin: pick a weapon, put your image on it and build the mod. It takes a minute.',
  'Разделы':
    'Sections',
  'Оружие, шапки, эффекты и звуки. Начнём с оружия.':
    'Weapons, hats, effects and sounds. Let\'s start with weapons.',
  'Выберите оружие':
    'Pick a weapon',
  'Нажмите сюда и выберите любое оружие.':
    'Click here and pick any weapon.',
  'Своя картинка':
    'Your image',
  'Перетащите картинку на текстуру или дважды щёлкните по ней, чтобы выбрать файл.':
    'Drag an image onto the texture, or double-click it to choose a file.',
  'Превью':
    'Preview',
  'Так скин будет выглядеть в игре. Модель можно крутить мышкой.':
    'This is how the skin will look in game. Rotate the model with the mouse.',
  'В руках':
    'In hand',
  'Можно посмотреть оружие от первого лица.':
    'You can see the weapon in first person.',
  'Вид':
    'View',
  'Показывать текстуру, модель или обе сразу.':
    'Show the texture, the model, or both.',
  'Своя настройка':
    'Own settings',
  'Шестерёнка задаёт отдельные настройки для этой текстуры. Нажмите её ещё раз, чтобы вернуться к общим.':
    'The gear gives this texture its own settings. Click it again to go back to the common ones.',
  'Правка материала и эффекты вроде свечения. Для обычного скина можно не трогать.':
    'Material editing and effects like glow. You can skip these for a regular skin.',
  'RED и BLU':
    'RED and BLU',
  'Отдельная текстура для RED и BLU.':
    'A separate texture for RED and BLU.',
  'Можно заменить модель на свою или раскрасить её по частям.':
    'You can replace the model with your own or paint it part by part.',
  'Нажмите «Параметры», чтобы открыть настройки сборки.':
    'Click "Parameters" to open the build settings.',
  'Настройки сборки':
    'Build settings',
  'Обычно хватает выбрать разрешение. Остальное можно оставить как есть. Закрывается той же кнопкой.':
    'Usually picking a resolution is enough. Leave the rest as is. The same button closes it.',
  'Сборка':
    'Build',
  'Соберите мод и положите файл в папку tf/custom игры.':
    'Build the mod and put the file into the game\'s tf/custom folder.',
  'Извлечь оригинальную текстуру, UV-шаблон и прочее.':
    'Extract the original texture, a UV template and more.',
  'Путь к игре, язык и тема. Здесь же можно пройти обучение ещё раз.':
    'Game path, language and theme. You can replay the tutorial here too.',
  'Остальное подскажу по ходу, когда дойдёте.':
    'I\'ll point out the rest as you get to it.',
  'Модель поделена на части. Наведите на номер, чтобы увидеть, где она.':
    'The model is split into parts. Hover a number to see where it is.',
  'Щёлкните по части, чтобы положить на неё картинку.':
    'Click a part to put an image on it.',
  'Красит часть в выбранный цвет.':
    'Paints a part with the chosen color.',
  'Цвет':
    'Color',
  'Выбор цвета. Там же градиент и пипетка.':
    'Pick a color. Gradient and eyedropper are there too.',
  'Ножницы':
    'Scissors',
  'Делят часть на части поменьше.':
    'Split a part into smaller ones.',
  'Обводит края покрашенных частей.':
    'Outlines the edges of painted parts.',
  'Кубик и ластик':
    'Die and eraser',
  'Случайная раскраска и сброс. Ctrl+Z отменяет.':
    'Random colors and reset. Ctrl+Z undoes.',
  'Выйти из режима частей.':
    'Leave parts mode.',
  'Подгоните свою модель под полупрозрачный оригинал. G — двигать, R — вращать, S — масштаб.':
    'Line your model up with the translucent original. G moves, R rotates, S scales.',
  'Числами':
    'By numbers',
  'То же самое, только точно.':
    'The same, but exact.',
  'Закончить подгонку.':
    'Finish fitting.',
  'Выберите шапку. Фильтр «Куда» сужает список: голова, лицо, тело.':
    'Pick a hat. The "Where" filter narrows the list: head, face, body.',
  'Всё как с оружием: перетащите картинку на текстуру.':
    'Same as weapons: drag an image onto the texture.',
  'Стили':
    'Styles',
  'У шапки несколько стилей. Каждый можно раскрасить отдельно.':
    'This hat has several styles. Each can be painted separately.',
  'Показывает, как шапка будет выглядеть с краской из игры.':
    'Shows how the hat will look with in-game paint.',
  'Если шапку носят несколько классов, при сборке спрошу, для каких.':
    "If several classes wear the hat, I'll ask which ones when you build.",
  'Эффекты':
    'Effects',
  'Выберите эффект. Необычные эффекты подписаны именами из игры, поиск находит и по имени системы.':
    'Pick an effect. Unusual effects carry their in-game names; search also finds system names.',
  'Эффект играет так же, как в игре. Мышью можно крутить.':
    'The effect plays just like in game. Rotate it with the mouse.',
  'Обычный режим':
    'Simple mode',
  'Главное: цвет, размер, скорость, время жизни. Правки сразу видно в кадре.':
    'The essentials: color, size, speed, lifetime. Changes show up right away.',
  'Все модули и параметры файла как есть. Нажмите, чтобы посмотреть.':
    'Every module and parameter of the file as is. Click to take a look.',
  'Параметров бывает под две сотни. Наберите часть имени, например radius.':
    'A system can have around two hundred parameters. Type part of a name, like radius.',
  'Новый параметр':
    'New parameter',
  'Щёлкните правой кнопкой по названию модуля и выберите «Добавить параметр…». В списке только то, чего в модуле ещё нет, а значение подставится как в игре.':
    'Right-click a module name and choose "Add a parameter…". The list only has what the module lacks, and the value comes in as the game uses it.',
  'Новый модуль':
    'New module',
  'Модуль — это целое поведение: вращение, цвет по времени, сила. Правая кнопка по заголовку группы — «Добавить модуль…».':
    'A module is a whole behavior: rotation, color over time, a force. Right-click a group header and choose "Add a module…".',
  'Правка':
    'Editing',
  'Правая кнопка по параметру — удалить или вернуть как в игре. Изменённое подсвечено.':
    'Right-click a parameter to delete it or revert to the game. Changes are highlighted.',
  'Системы':
    'Systems',
  'Эффект собран из систем. Правая кнопка по системе — переименовать, дублировать, добавить дочернюю.':
    'An effect is made of systems. Right-click a system to rename, duplicate or add a child.',
  'Текстуры':
    'Textures',
  'Текстуры эффекта. Перетащите картинку, чтобы заменить.':
    "The effect's textures. Drag an image onto one to replace it.",
  'Просмотр':
    'Playback',
  'Перезапуск, пауза и замедление. Ctrl+Z отменяет правку.':
    'Restart, pause and slow motion. Ctrl+Z undoes an edit.',
  'Контрольные точки: откуда эффект растёт и как движется. Можно повесить его на модель.':
    'Control points: where the effect starts and how it moves. You can attach it to a model.',
  'Соберите эффект в мод.':
    'Build the effect into a mod.',
  'Раскраска из игры, собранная в текстуру. Поверх можно дорисовать своё.':
    'An in-game paint baked into a texture. You can paint over it.',
  'Выберите раскраску, она сразу ляжет на модель.':
    'Pick a paint and it goes straight onto the model.',
  'Износ и сид':
    'Wear and seed',
  'Как в игре. Сид решает, как узор ляжет на оружие.':
    'Same as in game. The seed decides how the pattern lands on the weapon.',
  'Узоры разложены по деталям модели. Их можно перемешать или раздать вручную.':
    "Patterns are spread over the model's parts. Shuffle them or assign by hand.",
  'Раскраска станет обычной текстурой. Поверх неё можно дорисовать своё.':
    'The paint becomes a regular texture. You can paint over it.',
  'Выберите, что заменить: оружие, голоса или звуки мира.':
    'Choose what to replace: weapons, voices or world sounds.',
  'Фильтры':
    'Filters',
  'Помогают быстро найти нужный звук.':
    'Help you find the sound quickly.',
  'Замена':
    'Replacing',
  'Перетащите свой звук на строку или нажмите «Свой файл».':
    'Drop your sound onto a row or click "Own file".',
  'Все заменённые звуки соберутся в один мод.':
    'All replaced sounds are built into one mod.',
  // War Paint
  'Раскраска из игры: собирается в текстуру, которую можно дорисовать':
    'In-game paint: built into a texture you can keep painting on',
  'Износ': 'Wear',
  'Сид': 'Seed',
  'Случайный': 'Random',
  'От сида зависит, как узор ляжет на оружие: поворот, сдвиг, где износ':
    'The seed decides how the pattern lands on the weapon: rotation, offset, where the wear is',
  'Нанести': 'Apply',
  'Прямо с завода': 'Factory New',
  'Немного поношенное': 'Minimal Wear',
  'После полевых испытаний': 'Field-Tested',
  'Поношенное': 'Well-Worn',
  'Закалённое в боях': 'Battle Scarred',
  'У этого оружия нет War Paint': 'This weapon has no War Paints',
  'War Paint не собрался': 'The War Paint could not be built',
  'В игре нет части текстур War Paint: {}': 'Some War Paint textures are missing in the game: {}',
  'War Paint «{}»: собираю…': 'War Paint "{}": building…',
  'War Paint уже накладывается': 'A War Paint is already being applied',
  'Сначала выберите оружие': 'Choose a weapon first',
  'Оружие сменилось': 'The weapon was switched',
  // Выбор классов
  'Для каких классов собрать шапку': 'Which classes to build the hat for',
  'У каждого класса своя модель шапки. В мод попадут только отмеченные.':
    'Each class has its own hat model. Only the checked ones go into the mod.',
  'Никого': 'None',
  'Выбрано {} из {}': '{} of {} selected',
  'Разведчик': 'Scout',
  'Солдат': 'Soldier',
  'Поджигатель': 'Pyro',
  'Подрывник': 'Demoman',
  'Пулемётчик': 'Heavy',
  'Инженер': 'Engineer',
  'Медик': 'Medic',
  'Снайпер': 'Sniper',
  'Шпион': 'Spy',
  'У этого оружия в игре War Paint нет. Узоры разложены по деталям модели.':
    "This weapon has no War Paints in the game. The patterns are laid out over the model's parts.",
  'Перемешать детали': 'Shuffle parts',
  'Закрыть без изменений': 'Close without changes',
  'Раздать узоры деталям по-другому': 'Give the patterns to the parts differently',
  'Поиск раскраски': 'Search paints',
  'Раскраски': 'Paints',
  'Универсальный режим': 'Universal mode',
  'Этот War Paint не ложится на это оружие': "This War Paint doesn't fit this weapon",
  'Перемешиваю детали…': 'Shuffling parts…',
  // Раскладка по деталям (warpaint-layout.js)
  'Детали': 'Parts',
  'Настроить по деталям': 'Arrange by part',
  'Выбрать узор для каждой детали самому': 'Choose the pattern for each part yourself',
  'К раскраскам': 'Back to paints',
  'Вернуться к выбору раскраски (Esc)': 'Back to choosing a paint (Esc)',
  'Узоры': 'Patterns',
  'Мелкие — в основу': 'Small ones to base',
  'Детали меньше двух процентов развёртки — под основу': 'Parts under two percent of the UV map go to the base',
  'Перемешать': 'Shuffle',
  'Раздать узоры случайно: крупные детали получат разные': 'Hand out patterns at random: large parts get different ones',
  'Отменить последнее изменение раскладки (Ctrl+Z)': 'Undo the last layout change (Ctrl+Z)',
  'Вернуть раскладку, какую сделал автомат': 'Return to the automatic layout',
  'Разрезать деталь': 'Cut a part',
  'Детали крупные? Разрежьте их в «Частях модели» — здесь появятся новые': 'Parts too large? Cut them in Model parts — the new ones show up here',
  'Без узора': 'No pattern',
  'Основа': 'Base',
  'Узор {}': 'Pattern {}',
  'Группа {}': 'Group {}',
  'Участок {}': 'Area {}',
  'Деталь {}': 'Part {}',
  'Разбираю детали…': 'Reading the parts…',
  'Детали здесь — группы, как их разметили художники Valve.': "Parts here are the groups Valve's artists marked out.",
  'Детали — части модели, как их видно в «Частях модели».': 'Parts are the model parts, as seen in Model parts.',
  'Выберите узор и щёлкайте детали на модели или перетаскивайте строки на узоры.': 'Pick a pattern and click parts on the model, or drag rows onto patterns.',
  'Кисть — «{}». Щелчок по детали на модели кладёт этот узор.': 'Brush: “{}”. Clicking a part on the model lays this pattern.',
  'Родная текстура оружия, без узора': "The weapon's own texture, no pattern",
  'Первый узор шаблона: лежит везде, где не выбран другой': 'The first pattern of the template: it lies wherever no other is chosen',
  'Узор шаблона War Paint': 'War Paint template pattern',
  'Выбрано деталей: {}. Щёлкните узор или перетащите их на него.': 'Parts selected: {}. Click a pattern or drag them onto it.',
  'Узор выбран вручную': 'Pattern chosen by hand',
  'Узор выбрал автомат': 'Pattern chosen automatically',
  'Деталей: {}': 'Parts: {}',
  'Мелкие детали уже на основе': 'Small parts are already on the base',
  'Вернуться к War Paint': 'Back to War Paint',
  // Карта нормалей (normals.js)
  'Сила рельефа': 'Relief strength',
  'Насколько выпуклым выйдет рельеф из картинки': 'How raised the relief from the image will be',
  'Инвертировать': 'Invert',
  'Светлое станет вдавленным, тёмное — выпуклым': 'Light becomes recessed, dark becomes raised',
  'Заменить родной рельеф': 'Replace the original relief',
  'У этого предмета в игре своя карта нормалей. Обычно рельеф картинки ложится поверх неё': 'This item has its own normal map in the game. Normally the image relief is laid on top of it',
  'Нет текстуры, из которой строить рельеф': 'There is no texture to build the relief from',
  'Вернуться к раскладке War Paint — там уже новые детали': 'Back to the War Paint layout — the new parts are already there',
  'У модели нет развёртки — War Paint положить некуда': 'The model has no UV map — there is nowhere to put a War Paint',
  'Этот War Paint нарисован под одну пушку — его детали не переложить': "This War Paint is drawn for one weapon — its parts can't be rearranged",
  'В игре нет маски групп этой пушки': "The game has no group mask for this weapon",
  'Не удалось сохранить раскладку: {}': 'Could not save the layout: {}',
  'Раскрасок для этого оружия: {}': 'Paints for this weapon: {}',
  'Выберите раскраску — она сразу покажется на модели.': 'Pick a paint — it shows up on the model right away.',
  'Узор у команд разный — собирается под текущую команду': 'The pattern differs per team — built for the current team',
  'Собираю предпросмотр…': 'Building the preview…',
  'Предпросмотр на модели. «Нанести» соберёт в полном размере.': 'Preview on the model. "Apply" builds it at full size.',

  // ── Сообщения сервисов и воркеров: прогресс, ошибки, предупреждения ────
  // Приходят готовым текстом. Многострочные (итог сборки с предупреждениями,
  // ошибка VPK с подробностями) i18n.js переводит построчно.
  'Поиск модели...': 'Searching for the model...',
  'Проверка файлов игры...': 'Checking game files...',
  'Инициализация извлечения модели...': 'Starting model extraction...',
  'Извлечение модели...': 'Extracting the model...',
  'Извлечение модели: {}...': 'Extracting model: {}...',
  'Декомпиляция модели...': 'Decompiling the model...',
  'Извлечение завершено': 'Extraction complete',
  'Извлечение отменено пользователем': 'Extraction cancelled by the user',
  'Не удалось подобрать уникальное имя папки экспорта': "Couldn't find a free name for the export folder",
  'Не удалось подобрать уникальное имя файла экспорта': "Couldn't find a free name for the export file",
  'Извлечение файлов...': 'Extracting files...',
  'Завершено': 'Done',
  'Объединение отменено пользователем': 'Merge cancelled by the user',
  'не подобрать имя в библиотеке модов': "couldn't find a free name in the mod library",
  'Decompilation timed out after {}s: Crowbar завис на модели {}':
    'Decompilation timed out after {}s: Crowbar hung on model {}',
  'Compilation timed out after {}s: studiomdl завис на {}':
    'Compilation timed out after {}s: studiomdl hung on {}',
  'Читаю рецепт War Paint…': 'Reading the War Paint recipe…',
  'Наношу War Paint…': 'Applying War Paint…',
  'В игре нет файла War Paint (proto_defs.vpd)': 'The game has no War Paint file (proto_defs.vpd)',
  'srctools не установлен (pip install srctools)': 'srctools is not installed (pip install srctools)',
  '{} не найден в {}': '{} not found in {}',
  'файла нет': 'the file is missing',
  'внутри не MP3, а другой формат — игра его не прочитает':
    "it's not MP3 inside but another format — the game won't read it",
  'не WAV с обычным PCM: {}': 'not a plain PCM WAV: {}',
  'не прочитать: {}': "can't read it: {}",
  '{}-битный звук — игра играет только 16-битный': '{}-bit audio — the game only plays 16-bit',
  'частота {} Гц — игре нужна одна из {}': 'sample rate {} Hz — the game needs one of {}',
  'кадр APNG не того размера': 'an APNG frame has the wrong size',
  'Изображение не найдено: {}': 'Image not found: {}',
  'Не удалось извлечь ни одного кадра из VTF': "Couldn't extract a single frame from the VTF",
  'SMD файл не найден: {}': 'SMD file not found: {}',
  'Нет UV координат для отрисовки': 'No UV coordinates to draw',
  'Файл не найден: {}': 'File not found: {}',
  'Файл занят другим процессом: {}': 'The file is in use by another process: {}',
  'Ошибка создания VPK файла': 'Error creating the VPK file',
  'Ошибка создания VTF файла\nКоманда: {}': 'Error creating the VTF file\nCommand: {}',
  'Имя файла не может быть пустым': 'The file name cannot be empty',
  'Имя файла слишком короткое (минимум {} символ)': 'The file name is too short (at least {} character)',
  'Имя файла слишком длинное (максимум {} символов)': 'The file name is too long (at most {} characters)',
  'Имя файла должно заканчиваться на .vpk': 'The file name must end with .vpk',
  'Недопустимый символ: {}': 'Invalid character: {}',
  'Недопустимый путь: {}': 'Invalid path: {}',
  'VPK файл не найден: {}': 'VPK file not found: {}',
  'VPK файл: {}': 'VPK file: {}',
  'MDL файл не найден в VPK: {}': 'MDL file not found in the VPK: {}',
  'Не удалось открыть VPK файл {}': "Couldn't open VPK file {}",
  'Не удалось открыть VPK файл {}: {}': "Couldn't open VPK file {}: {}",
  'Не удалось извлечь .mdl файл: {}': "Couldn't extract the .mdl file: {}",
  'Проверьте, что путь правильный и файл существует в VPK.':
    'Check that the path is correct and the file exists in the VPK.',
  'Ожидаемый путь в VPK: {}': 'Expected path in the VPK: {}',
  'Директория извлечения: {}': 'Extraction folder: {}',
  'Попробуйте проверить содержимое VPK через GCFScape.': 'Try checking the VPK contents with GCFScape.',
  'Библиотека vpk не установлена. Установите её через: pip install vpk':
    'The vpk library is not installed. Install it with: pip install vpk',
  'Если библиотека vpk не установлена, установите её: pip install vpk':
    'If the vpk library is not installed, install it: pip install vpk',
  'отменено': 'cancelled',
  'размер не совпал: {} вместо {}': 'size mismatch: {} instead of {}',
  'контрольная сумма не совпала — файл повреждён': 'checksum mismatch — the file is corrupted',
  'установщик не найден: {}': 'installer not found: {}',
  'установка поддерживается только на Windows': 'installing is only supported on Windows',
  // Гирлянды: причина подставляется в «Гирлянда {} не собралась: {}».
  'Гирлянда {} не собралась: {}': "The {} garland didn't build: {}",
  '{} нет в игре': '{} is not in the game',
  'в разборе {} нет QC или меша': 'the decompiled {} has no QC or mesh',
  'в QC нет $cdmaterials': 'the QC has no $cdmaterials',
  'VTF для {} не создался': "the VTF for {} wasn't created",
  // Предупреждения сборки: строками под «Внимание:» в итоге сборки.
  'Не найдена игровая текстура \'{}\' — в игре материал может быть фиолетовым. Загрузите свою текстуру в главный слот.':
    "Game texture '{}' not found — the material may be purple in game. Load your own texture into the main slot.",
  'Не найдена оригинальная текстура плеч \'{}\' — плечи вьюмодели могут быть фиолетовыми.':
    "Original shoulder texture '{}' not found — the viewmodel shoulders may be purple.",
  'Стили шапки делят материал \'{}\': в игре они не могут выглядеть по-разному, в мод попадёт одна текстура.':
    "Hat styles share material '{}': they can't look different in game, so one texture goes into the mod.",
  'Замена модели не выполнена: не найден reference SMD для {}. В мод попадёт оригинальная геометрия.':
    "Model replacement skipped: no reference SMD for {}. The original geometry goes into the mod.",
  'Замена модели завершилась ошибкой — в мод попадёт оригинальная модель. ({})':
    'Model replacement failed — the original model goes into the mod. ({})',
  '\'{}\' — это навесное украшение (гирлянда), а не сам ствол: игра рисует его поверх базового оружия. Красится только украшение; чтобы изменить сам ствол, соберите базовое оружие.':
    "'{}' is an attached decoration (a garland), not the weapon itself: the game draws it over the base weapon. Only the decoration gets painted; to change the weapon itself, build the base weapon.",
  'Временные файлы сохранены в: {}': 'Temporary files kept in: {}',
};
