import * as THREE from 'three';

// Собирает модель Солдата из BoxGeometry-примитивов.
// Все размеры в условных единицах, солдат занимает высоту ~88 единиц (y 0..88)
export function buildSoldierGroup() {
  const group = new THREE.Group();

  const matBody   = new THREE.MeshLambertMaterial({ color: 0x575750 }); // хаки
  const matDark   = new THREE.MeshLambertMaterial({ color: 0x3a3830 }); // тёмный (ботинки/шлем)
  const matHelmet = new THREE.MeshLambertMaterial({ color: 0x2e3028 }); // шлем

  // [ширина, высота, глубина, центр_x, центр_y, центр_z, материал]
  const parts = [
    // Ботинки
    [8, 10, 14, -5,    5,  0,  matDark],
    [8, 10, 14,  5,    5,  0,  matDark],
    // Ноги
    [7, 28, 10, -5,   24,  0,  matBody],
    [7, 28, 10,  5,   24,  0,  matBody],
    // Торс
    [24, 24, 14,  0,  51,  1,  matBody],
    // Плечи
    [ 8,  8, 11,-14,  63,  0,  matBody],
    [ 8,  8, 11, 14,  63,  0,  matBody],
    // Руки
    [ 6, 28,  8,-15,  50,  0,  matBody],
    [ 6, 28,  8, 15,  50,  0,  matBody],
    // Шея
    [ 6,  5,  6,  0,  68,  0,  matBody],
    // Голова
    [14, 12, 14,  0,  75,  0,  matBody],
    // Шлем (поля + тулья)
    [20,  4, 20,  0,  82,  1,  matHelmet],
    [16,  8, 16,  0,  86,  0,  matHelmet],
  ];

  parts.forEach(([w, h, d, x, y, z, mat]) => {
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat);
    mesh.position.set(x, y, z);
    group.add(mesh);
  });

  return group;
}
