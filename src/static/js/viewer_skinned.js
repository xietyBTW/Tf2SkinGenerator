// Сборка анимированной вьюмодели из данных, присланных Python.
//
// Статичная поза приходит готовым OBJ — для одного кадра это проще всего.
// Анимацию так не отдать, поэтому меш приходит один раз в bind-позе, а
// движение — дорожками костей (см. services/viewmodel_animation.py).
//
// Скелет в сцене ОДИН — рук. Оружие своего не имеет: каждая его вершина
// подвешена к той кости руки, которая её ведёт, и геометрия прислана уже
// запечённой в bind-позу руки. Поэтому обе части биндятся к одному скелету, и
// одного микшера хватает на всю сцену.
//
// Оси Source разворачивает в оси Three.js один поворот корневой группы; сами
// кости не трогаем — вторая конвертация была бы вторым источником ошибок.
//
// THREE передаётся параметром (как в viewer_materials.js): так модуль
// проверяется на Node с заглушкой вместо настоящей библиотеки.

// Собирает сцену.
//
//   THREE        — библиотека
//   data         — то, что прислал viewmodel_animation.build_scene
//   makeMaterial — (имяМатериала) → THREE.Material
//
// Возвращает { group, skeleton, mixer, action, meshes, duration }.
// meshes — [{ name, mesh }] по материалам, чтобы вьювер мог менять текстуры
// по имени материала ровно так же, как в обычном превью.
export function buildSkinnedScene(THREE, data, makeMaterial) {
  const bones = createBones(THREE, data.bones || []);
  const group = new THREE.Group();
  group.rotation.x = Number(data.rootRotationX) || 0;

  // Корни добавляем ДО создания скелета: THREE.Skeleton берёт обратные
  // матрицы из текущих мировых, а те считаются только после updateMatrixWorld.
  for (const bone of bones) {
    if (bone.userData.parentIndex < 0) group.add(bone);
  }
  group.updateMatrixWorld(true);

  const skeleton = new THREE.Skeleton(bones);
  const meshes = [];
  for (const part of data.parts || []) {
    for (const entry of createPart(THREE, part, makeMaterial)) {
      group.add(entry.mesh);
      meshes.push(entry);
    }
  }
  // Биндим СТРОГО после добавления в группу и обновления мировых матриц.
  // bind() без явной матрицы берёт текущую mesh.matrixWorld как bindMatrix, а
  // у не добавленного меша она единичная — и поворот группы (оси Source →
  // оси Three.js) применялся дважды: руки растягивало в шипы.
  group.updateMatrixWorld(true);
  for (const { mesh } of meshes) {
    mesh.bind(skeleton, mesh.matrixWorld);
  }

  // Реквизит насмешки в кадре не всё время: игра прячет и достаёт его
  // событиями AE_WPN_HIDE/UNHIDE, а Python переводит их в секунды клипа
  // (см. taunt_worker.hidden_ranges). Медик до 23-го кадра только лезет за
  // снимком за пазуху — без этого снимок висел бы в руке с самого начала.
  const hidden = data.weaponHidden || [];
  const built = { group, skeleton, mixer: new THREE.AnimationMixer(group),
                  action: null, meshes, duration: 0, hidden,
                  props: hidden.length
                    ? meshes.filter(e => e.kind === 'weapon').map(e => e.mesh)
                    : [] };
  applyClip(THREE, built, data.clip);
  return built;
}

// Меняет проигрываемую анимацию на УЖЕ собранной сцене.
//
// Меш, скелет, материалы и текстуры у одного оружия одни и те же — от выбора
// анимации зависят только дорожки. Пересобирать ради них всю сцену значит
// заново распаковывать текстуры и перечитывать SMD.
//
// Возвращает новое действие либо null, если дорожек нет.
export function applyClip(THREE, built, clipData) {
  if (!built || !built.mixer) return null;
  if (built.action) {
    built.mixer.stopAllAction();
    built.mixer.uncacheClip(built.action.getClip());
    built.action = null;
    built.duration = 0;
  }
  const clip = createClip(THREE, clipData, built.skeleton.bones);
  if (!clip) return null;
  const action = built.mixer.clipAction(clip);
  // Повторяем ВСЕГДА, даже то, что в игре играется один раз. В превью «достать
  // оружие» или выстрел нужно рассмотреть, а однократный показ этого не даёт.
  action.setLoop(THREE.LoopRepeat, Infinity);
  action.play();
  built.action = action;
  built.duration = clip.duration;
  return action;
}

// Прячет и показывает реквизит по времени клипа. Зовётся каждый кадр.
export function updateHidden(built) {
  if (!built || !built.props || !built.props.length || !built.action) return;
  const t = built.action.time;
  // Конец null значит «до конца клипа»: последний AE_WPN_HIDE пары не имеет.
  const off = built.hidden.some(
    ([from, to]) => t >= from && (to === null || t < to));
  for (const mesh of built.props) mesh.visible = !off;
}


// Кости в bind-позе. Порядок из Python гарантирует, что родитель уже создан.
export function createBones(THREE, list) {
  const bones = [];
  list.forEach((spec, index) => {
    const bone = new THREE.Bone();
    bone.name = spec.name;
    bone.position.set(...(spec.position || [0, 0, 0]));
    bone.quaternion.set(...(spec.quaternion || [0, 0, 0, 1]));
    bone.userData.parentIndex = spec.parent >= 0 ? spec.parent : -1;
    if (bone.userData.parentIndex >= 0 && bones[bone.userData.parentIndex]) {
      bones[bone.userData.parentIndex].add(bone);
    }
    bones[index] = bone;
  });
  return bones;
}

// Один меш на материал: так вьювер меняет текстуры по имени материала — тем же
// путём, что и в обычном превью, где каждой группе OBJ соответствует свой меш.
function createPart(THREE, part, makeMaterial) {
  const out = [];
  for (const group of part.groups || []) {
    const geometry = new THREE.BufferGeometry();
    const from = group.start * 3;
    const to = (group.start + group.count) * 3;
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(
      (part.positions || []).slice(from, to), 3));
    geometry.setAttribute('normal', new THREE.Float32BufferAttribute(
      (part.normals || []).slice(from, to), 3));
    geometry.setAttribute('uv', new THREE.Float32BufferAttribute(
      (part.uvs || []).slice(group.start * 2, (group.start + group.count) * 2), 2));
    geometry.setAttribute('skinIndex', new THREE.Uint16BufferAttribute(
      (part.skinIndex || []).slice(group.start * 4, (group.start + group.count) * 4), 4));
    geometry.setAttribute('skinWeight', new THREE.Float32BufferAttribute(
      (part.skinWeight || []).slice(group.start * 4, (group.start + group.count) * 4), 4));

    const mesh = new THREE.SkinnedMesh(geometry, makeMaterial(group.material));
    mesh.name = group.material;
    mesh.frustumCulled = false;   // вьюмодель всегда перед камерой
    out.push({ name: group.material, mesh, kind: part.kind });
  }
  return out;
}

// Дорожки кадров → THREE.AnimationClip.
export function createClip(THREE, clip, bones) {
  if (!clip || !clip.times || clip.times.length === 0) return null;
  const tracks = [];
  for (const track of clip.tracks || []) {
    // По имени надёжнее: клип может приходить отдельно от сцены, и полагаться
    // на совпадение порядка костей в двух посылках не стоит.
    const bone = (track.name && bones.find(b => b.name === track.name))
              || bones[track.bone];
    if (!bone) continue;
    if (track.positions && track.positions.length) {
      tracks.push(new THREE.VectorKeyframeTrack(
        `${bone.name}.position`, clip.times, track.positions));
    }
    if (track.quaternions && track.quaternions.length) {
      tracks.push(new THREE.QuaternionKeyframeTrack(
        `${bone.name}.quaternion`, clip.times, track.quaternions));
    }
  }
  if (tracks.length === 0) return null;
  // `hold` — сколько держать последний кадр. Отдельной логики он не требует:
  // за концом дорожки three.js отдаёт её последнее значение, поэтому лишние
  // секунды в длине клипа и есть застывшая поза (см. build_scene.clip_hold).
  const duration = clip.duration
    ? clip.duration + (Number(clip.hold) || 0)
    : -1;
  return new THREE.AnimationClip(clip.name || 'viewmodel', duration, tracks);
}
