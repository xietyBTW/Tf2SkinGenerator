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
  'Классы для сборки': 'Classes to build',
  'Положить работу в раздел «Кастомный мод»':
    'Put this work into the “Custom mod” section',
  'У предмета остались отложенные правки': 'This item has edits set aside',
  'Удалить сохранённые правки этого предмета':
    'Delete the saved edits of this item',
  'Для каких классов положить шапку в мод. У каждого своя модель — снятые классы в мод не попадут':
    'Which classes to put into the mod. Each has its own model — unchecked classes are left out',
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
  'Вставить ▾': 'Insert ▾',
  'Как в игре': 'As in the game',
  'Применить шаблон': 'Apply the template',
  'Заменить весь VMT этим шаблоном?': 'Replace the whole VMT with this template?',
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
  'Дробление': 'Detail',
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
  'Свести отмеченные отрезки в одну часть':
    'Merge the marked pieces into one part',
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
  'Отмечать можно только отрезанное: сперва отрежь на модели':
    'Only cut pieces can be marked: cut it on the model first',
  'Отмечено {}. «Объединить» сведёт их в одну часть': 'Marked {}. “Merge” will bring them into one part',
  '. То же — щелчок по ней на модели с ножницами':
    '. Same as clicking it on the model with the scissors',
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
  'Наведи на модель — обведётся кусок развёртки, который отрежется. Щелчок режет; щелчки по отрезанным в списке отмечают их, чтобы свести в одну часть':
    'Hover the model to outline the UV piece that will be cut. A click cuts it; clicking pieces already cut marks them so they can be merged into one part',
  'Объединяю…': 'Merging…',
  'Отрезки сведены в одну часть': 'The pieces are merged into one part',
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
  'Контур': 'Outline',
  'Приблизить холст к куску: класть картинку, глядя на всю текстуру, — целиться в спичку с другого конца комнаты':
    'Zoom the canvas to the piece: placing an image while looking at the whole texture is like aiming at a match from across the room',
  'Спрятать игровую текстуру: на пёстрой не видно границ своей картинки':
    'Hide the game texture: on a busy one the edges of your image are hard to see',
  'Только внешний контур куска вместо сетки треугольников':
    'Only the outer outline of the piece instead of the triangle mesh',
  'Тяни мышью · размер — за квадратики · поворот — за маркер или стрелками · колесо — ближе':
    'Drag with the mouse · size — by the squares · rotate — by the handle or arrow keys · wheel — closer',
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
  'руки': 'hands',
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
};
