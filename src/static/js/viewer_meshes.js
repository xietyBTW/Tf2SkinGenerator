// Что пользователю разрешено перекрашивать.
//
// В обычном превью — вся модель. В сцене вида от первого лица рядом с оружием
// стоят руки класса: они стоковые и чужие, а пользовательская текстура
// относится к оружию. Пока этого различия не было, дроп на руки красил руки, а
// подсветка под курсором это ещё и обещала.
//
// Ограничение задаёт Python (setEditableMeshNames) по именам материалов
// оружия. Пустое ограничение означает «можно всё» — это обычное превью, и его
// поведение не меняется.
//
// Модуль чистый (без THREE) — чтобы его считал тест на Node.

// Разрешено ли трогать этот меш.
//
// Имя меша в OBJ берётся из группы `g`, и оно совпадает с именем материала.
// Проверяем оба на случай, если загрузчик назовёт меш иначе.
export function isEditableMesh(mesh, editableNames) {
  if (!editableNames || editableNames.size === 0) return true;
  if (!mesh) return false;
  if (editableNames.has(mesh.name)) return true;
  const material = mesh.material;
  const matName = material && !Array.isArray(material) ? material.name : '';
  return Boolean(matName) && editableNames.has(matName);
}

// Первый по лучу меш, который разрешено перекрашивать.
//
// Нередактируемые пропускаются НАСКВОЗЬ, а не блокируют дроп: закрытая руками
// часть ствола всё равно должна принимать текстуру.
export function firstEditableHit(hits, editableNames) {
  for (const hit of hits || []) {
    const mesh = hit && hit.object;
    if (mesh && isEditableMesh(mesh, editableNames)) return mesh;
  }
  return null;
}
