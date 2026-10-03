# Sounds

[Documentation](../README.md) · [Русская версия](../ru/sounds.md)

The **Sounds** section replaces game sounds with your own files: gunshots, reloads, hit sounds, voice lines, footsteps, music. The app builds a VPK that puts your files where the game looks for its own.

## How the game finds a sound

The game doesn't play a sound by file name. Its code asks for an *entry* such as `Weapon_Shotgun.Single`, and the sound scripts say which file or files that entry plays. A mod changes the sound by putting a file with the same path into `sound/`.

That's why the list in this section is a list of entries, not files. Each row is one entry: its name, the event it belongs to, the item or speaker, and the files it plays. Two details follow from this:

- **An entry can have several files.** The game picks one at random so the sound doesn't get repetitive. Replacing the entry replaces all of them, otherwise you'd hear your sound only part of the time. You can also replace them one by one.
- **A file can belong to several entries.** The bat's miss sound, for instance, is shared by many melee weapons. Replacing the file changes it everywhere, and the row says so: **shared by N**, with the other entries listed when you expand the row.

Voice lines with numbered takes (`Scout.Go01` to `Scout.Go08`) are folded into one row, so the list stays readable.

## Finding the right entry

**Sections** at the top split the sounds into **Weapons**, **Voice**, **Player** and **World**. Switching the section resets the other filters, because each section has its own events and speakers.

**Search** (**Name, item or file**) matches item names in both languages, model names, classes, events, entry names and file paths. Every word has to match somewhere. Results are sorted by relevance: a match on a whole name ranks higher than a match inside a file path. When a section has nothing for your search, the app tells you which other section does.

**Filters** on the left narrow the list, and each value shows how many entries it leaves:

| Filter | What it does |
|---|---|
| **Class** | The class or the speaker: the nine classes, **Announcer**, **Miss Pauling**, **Halloween**, **Ap-Sap**, **Other**. |
| **Event** | What the sound is for. For weapons: **Fire**, **Crit**, **Reload**, **Hit**, **Draw**, **Explosion**, **Spin-up**, **Healing**, **Buildings**, **Hit sound** and more. For voice lines: **Voice commands**, **Auto responses**, **Domination**, **Laughter**, **Taunts**, **Death**, **Pain** and more. In the **Player** and **World** sections this filter is called **Type** (**Footsteps**, **Music**, **Ambience**, **Interface** and others). |
| **Variant** | **Regular** or **MvM robots**. |
| **Format** | **WAV** or **MP3**. |
| **Own** → **Replaced** | Only the entries you've already changed. |

The list loads in portions of about four hundred rows; **Show N more** at the bottom loads the next ones.

## Listening

**Play** on a row plays its sound in the player at the bottom of the page, with a seek bar, time and **Volume**. After you replace a sound, **Play** plays your file and **Original** plays the game's one, so you can compare.

Clicking the file name in a row expands it. You see each file of the entry with its own buttons, and above them how the game plays the entry: channel, sound level, volume and pitch. Your file will be played with the same settings.

The list works from the keyboard as well: <kbd>↑</kbd> and <kbd>↓</kbd> move between rows, <kbd>Space</kbd> plays, <kbd>Enter</kbd> asks for your own file, <kbd>Delete</kbd> removes it, <kbd>Esc</kbd> returns to the search box. <kbd>↓</kbd> in the search box jumps into the list.

## Replacing a sound

Click **Own file** on a row and choose an audio file, or drop the file onto the row. To replace only one file of an entry, expand the row and use **Own file** on that file, or drop onto it.

A replaced row is marked **Replaced**, or **Partly** if only some of its files are yours. **Remove** takes your file off.

**Save** puts the game's original into the export folder, which is handy when you want to edit it instead of starting from scratch. For an entry with several files, all of them are saved.

### Formats the game accepts

The engine picks the decoder by the file extension written in the entry, not by what's inside the file. A WAV renamed to `.mp3` simply stays silent. The app takes care of this:

| The entry plays | What you can give it |
|---|---|
| `.wav` | Almost any audio file. The app converts it to a mono 16-bit WAV at 44,100 Hz before storing it. |
| `.mp3` (most voice lines) | Only a real MP3 file. The app can't encode MP3, so convert the file yourself first. |

The app also checks ready WAV files: the game plays only 16-bit sound at 11,025, 22,050 or 44,100 Hz. If a file doesn't fit, the message under the list explains why.

When an entry mixes formats, your file goes only onto the files of the matching format, and the message says how many stayed as they are.

## Building the sound mod

The footer counts your files (**Your files: N**). **Clear all** removes every replacement at once. Type a name in the **VPK name** field (`sounds_mod` by default) and press **Build VPK**. All replaced sounds go into one mod in the export folder.

Install it like any other mod: put the `.vpk` into `tf/custom` and restart the game.

> [!NOTE]
> Sound files are protected by `sv_pure`, so on casual servers the game plays its own sounds. Sound mods work in local games and on servers that allow custom content.

## See also

- [Installing mods and troubleshooting](troubleshooting.md)
- [Settings and data folders](settings.md): where the export folder is.
