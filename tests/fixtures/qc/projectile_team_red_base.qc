// Снаряд: база col0 уже несёт суффикс _red (w_grenade_red → w_grenade_blue).
// blu_is_team должен распознать команду и по этому паттерну, а не только
// «нейтраль → X_blue».
$texturegroup "skinfamilies"
{
	{ "w_grenade_red"  "w_grenade_blue" }
	{ "w_grenade_blue" "w_grenade_blue" }
}
