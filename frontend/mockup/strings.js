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
 * mod.vpk»), а не её кусок. Ключи, кончающиеся на «:» или «…», работают ещё и
 * началом строки: к ним обычно дописывают значение.
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
  'c_scattergun · Scout · 4 материала': 'c_scattergun · Scout · 4 materials',
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
  'Раздел «': 'Section “',
  '» ещё не подключён.': '” is not wired up yet.',
  'Эффект': 'Effect',
  'Файл частиц': 'Particle file',
  'Файл не выбран': 'No file selected',
  'Выберите файл — в нём десятки эффектов.':
    'Pick a file — it holds dozens of effects.',
  'Выберите систему частиц.': 'Select a particle system.',

  // ── Библиотека модов и работы ─────────────────────────────────────────
  'Свои работы и моды из VPK. Предмет из списка оружия открывается игровым — сохранённая работа открывается отсюда.':
    'Your saved works and VPK mods. An item picked from the weapons list opens as it is in the game — a saved work opens from here.',
  'Открыть VPK-мод…': 'Open a VPK mod…',
  'файл с диска': 'file from disk',
  'Убрать из библиотеки (исходный файл останется)':
    'Remove from the library (the source file stays)',
  'Убрать мод из библиотеки': 'Remove the mod from the library',
  'Удалится копия в библиотеке. Исходный файл, который вы открывали, останется на месте.':
    'The library copy will be deleted. The source file you opened stays where it is.',
  'Убрать': 'Remove',
  'сегодня': 'today',
  'вчера': 'yesterday',
  'день': 'day',
  'дня': 'days',
  'дней': 'days',
  'назад': 'ago',
  'сохранённая работа': 'saved work',
  'Открываю работу…': 'Opening the work…',
  'Разбор': 'Reading',
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
  'Опции': 'Options',
  'Гамма-коррекция': 'Gamma correction',
  'Изолировать плечи': 'Isolate shoulders',
  'Краски из игры': 'Game paints',
  'Останавливаю сборку…': 'Stopping the build…',
  'Сборка…': 'Building…',
  'Ошибка сборки': 'Build failed',
  'Чем красить «': 'What to put on “',
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
  'И так для остальных — ещё': 'Same for the rest — {} more',
  'материал': 'material',
  'материала': 'materials',
  'материалов': 'materials',
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
  'Нет связи с Python:': 'No connection to Python:',
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
  'Эти материалы не показываются в альбоме и не пишутся в мод.':
    'These materials are not shown in the album and are not written into the mod.',
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
  'Сейчас в кэше': 'The cache now holds',
  '. Кэш ускоряет повторную сборку того же оружия — после очистки первая сборка каждого будет медленнее.':
    '. The cache speeds up rebuilding the same weapon — after clearing, the first build of each will be slower.',
  'Кэш очищен, записей удалено:': 'Cache cleared, entries removed:',
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
  'Черновиков удалено:': 'Drafts deleted:',

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
  'Что делать:': 'What to do:',

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
  'Конвертация': 'Converting',
  'Что это за модель': 'What kind of model is this',
  'Материалы модели:': 'Model materials:',
  'Материалов в модели не нашлось.': 'No materials found in the model.',
  'Готовая — со своими материалами': 'Finished — with its own materials',
  'Карточки возьмутся из самой модели, будет доступна правка QC':
    'The cards come from the model itself, and QC editing becomes available',
  'Только геометрия — текстуры игровые':
    'Geometry only — the textures stay from the game',
  'На экране ваша геометрия, карточки из игрового QC':
    'Your geometry on screen, cards from the game QC',
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
  'Загрузка стиля:': 'Loading the style:',
  'Загрузка модели…': 'Loading the model…',
  'Загрузка текстуры…': 'Loading the texture…',
  'Сборка сцены:': 'Building the scene:',
  'Собираем сцену…': 'Building the scene…',
  'Сборка вида от первого лица…': 'Building the first-person view…',
  'Извлечение граней неба…': 'Extracting the sky faces…',
  'Не удалось показать модель:': 'Could not show the model:',
  'Не удалось показать сцену:': 'Could not show the scene:',
  'Не удалось загрузить:': 'Could not load:',
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

  // ── Части модели ──────────────────────────────────────────────────────
  'Части': 'Parts',
  'Кисть': 'Brush',
  'Нарезка': 'Cutting',
  'Окантовка': 'Outline',
  'Градиент': 'Gradient',
  'Сила': 'Strength',
  'Резать': 'Cut',
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
  'Направление перехода:': 'Gradient direction:',
  'Щёлкать по кускам модели, чтобы дробить их мельче':
    'Click parts of the model to cut them finer',
  'Свести отмеченные отрезки в одну часть':
    'Merge the marked pieces into one part',
  'Обвести края покрашенных частей': 'Outline the edges of painted parts',
  'Цвет окантовки': 'Outline color',
  'Эта модель — один цельный кусок, делить нечего':
    'This model is a single solid piece, there is nothing to split',
  'Щёлкай по кускам модели — покрасятся. Нарезать мельче или обвести края — вкладками слева':
    'Click the pieces of the model to paint them. Cut finer or outline the edges with the tabs on the left',
  'Красить этим цветом': 'Paint with this color',
  'Щёлкай по частям модели — покрасятся в этот цвет':
    'Click the parts of the model to paint them this color',
  'Перетащи картинку на часть модели или выбери цвет':
    'Drag an image onto a part of the model, or pick a color',
  'Часть': 'Part',
  'Часть ': 'Part ',
  ' развёртки': ' of the UV map',
  'часть': 'part',
  'развёртки': 'of the UV map',
  '· развёртка': '· UV map',
  'тр.': 'tri',
  'Делит развёртку с другими: в игре они покрасятся вместе, разными их сделать нельзя':
    'Shares the UV map with others: in the game they are painted together and cannot be made different',
  'Прирастить обратно': 'Grow it back',
  'Как положена картинка: размер, поворот, место':
    'How the image is placed: size, rotation, position',
  'Вернуть этой части игровую текстуру':
    'Bring back the game texture for this part',
  'У этого куска один остров развёртки — резать нечего':
    'This piece has a single UV island — there is nothing to cut',
  'Режу…': 'Cutting…',
  'Отрезано': 'Cut off',
  'остров': 'island',
  'острова': 'islands',
  'островов': 'islands',
  'из': 'of',
  '. Вернуть — щелчок по нему же или «−» на его чипе':
    '. To bring it back click it again, or press “−” on its chip',
  'Отмечать можно только отрезанное: сперва отрежь на модели':
    'Only cut pieces can be marked: cut it on the model first',
  'Отмечено': 'Marked',
  '. «Объединить» сведёт их в одну часть':
    '. “Merge” will bring them into one part',
  '. То же — щелчок по ней на модели в режиме «Резать»':
    '. Same as clicking it on the model in “Cut” mode',
  'Наложение на часть…': 'Placing on the part…',
  'Эта часть делит развёртку с соседними — они покрасились вместе':
    'This part shares the UV map with its neighbours — they were painted together',
  'Не удалось:': 'Failed:',
  'Перерезаю модель…': 'Re-cutting the model…',
  'Частей:': 'Parts:',
  'Случайная раскраска — щёлкай по частям, чтобы поправить':
    'Random coloring — click the parts to fix it up',
  'Отменено': 'Undone',
  'Наведи на модель — обведётся кусок развёртки, который отрежется. Щелчок режет; щелчки по отрезанным в списке отмечают их, чтобы свести в одну часть':
    'Hover the model to outline the UV piece that will be cut. A click cuts it; clicking pieces already cut marks them so they can be merged into one part',
  'Объединяю…': 'Merging…',
  'Отрезки сведены в одну часть': 'The pieces are merged into one part',
  'Обвожу края…': 'Outlining the edges…',
  'Убираю окантовку…': 'Removing the outline…',
  'Градиент: щёлкай по частям — переход из первого цвета. Направление задаёт ручка':
    'Gradient: click the parts to fill them from the first color. The handle sets the direction',
  'Перекладываю…': 'Re-placing…',

  // ── Посадка картинки на часть ─────────────────────────────────────────
  'Как положить картинку': 'How to place the image',
  'Вписать': 'Fit',
  'Целиком': 'Whole',
  'Заполнить': 'Fill',
  'Растянуть': 'Stretch',
  'Размер': 'Size',
  'Приблизить': 'Zoom',
  'Без игровой': 'No game texture',
  'Тяни картинку мышью, поворачивай за маркер сверху (стрелки — на 15°), колесо — приблизить к курсору':
    'Drag the image with the mouse, rotate it by the handle on top (arrows turn it by 15°), the wheel zooms to the cursor',
  'Отменить правку (Ctrl+Z)': 'Undo (Ctrl+Z)',
  'Вернуть правку (Ctrl+Y)': 'Redo (Ctrl+Y)',

  // ── Инструменты ───────────────────────────────────────────────────────
  'Загрузка': 'Loading',
  'Не удалось открыть:': 'Could not open:',
  'Куда сохранить PCF': 'Where to save the PCF',
  'Сохранено: {} ({} Б)': 'Saved: {} ({} B)',
  'Сбор справочника…': 'Collecting the reference…',
  'Справочник сохранён: {}': 'Reference saved: {}',
  'Построение UV-шаблона…': 'Building the UV template…',
  'UV-шаблон не построен': 'The UV template was not built',
  'UV-шаблон': 'UV template',
  'UV-шаблон:': 'UV template:',
  'UV-шаблоны:': 'UV templates:',
  'шт.': 'pcs.',
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
  'Один перекроет другой. Продолжить?': 'One will override the other. Continue?',
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
  'Точки': 'Points',
  'Вернуть': 'Restore',
  'Свернуть': 'Collapse',
  'Развернуть': 'Expand',
  '{} · дочерних: {}': '{} · children: {}',
  ' систем, корней ': ' systems, roots ',
  'В этом файле систем нет.': 'This file has no systems.',
  'система': 'system',
  'не в превью': 'not in the preview',
  'эффекту нужны:': 'the effect needs:',
  'Эту точку эффект использует': 'The effect uses this point',
  'В кэше нет разобранных моделей — откройте модель на вкладке оружия или шапок, и она появится здесь':
    'The cache has no decompiled models — open a model on the weapons or cosmetics tab and it will show up here',
  'Модель из кэша декомпиляции': 'A model from the decompile cache',
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
  'Какой параметр': 'Which parameter',
  'Значение подставится такое, как в эффектах игры.':
    'The value is taken from the game effects.',
  'Параметры скопированы — можно вставить в другую систему или отдать ИИ':
    'Parameters copied — paste them into another system or hand them to an AI',
  'Скопируйте набор параметров': 'Copy the parameter set',
  'Буфер обмена недоступен — выделите и скопируйте.':
    'The clipboard is not available — select and copy by hand.',
  'Вставьте набор параметров': 'Paste the parameter set',
  'JSON с ключом tf2sgParticleParams': 'JSON with a tf2sgParticleParams key',
  'В буфере не JSON:': 'The clipboard does not hold JSON:',
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
  'Вставлено, но часть пропущена:': 'Pasted, but some of it was skipped:',
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
};
