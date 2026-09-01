// Оружие с подвижными частями: в руку садятся только две кости из шести.
$modelname "weapons/c_models/c_revolver.mdl"
$cdmaterials "models\weapons\c_models\c_revolver\"

$definebone "weapon_bone" "" 0 0 0 0 0 0 0 0 0 0 0 0
$definebone "weapon_bone_1" "weapon_bone" 0.35 0.80 2.97 0 90 0 0 0 0 0 0 0
$definebone "c_weapon_stattrack" "weapon_bone" 0.67 1.53 5.87 0 -9 -91 0 0 0 0 0 0

$bonemerge "weapon_bone"
$bonemerge "c_weapon_stattrack"
