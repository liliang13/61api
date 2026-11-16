export function createPackageId(existing = []) {
  const used = new Set(existing.map((pkg) => String(pkg.id || '').trim()))
  let n = 1
  while (used.has(`p${n}`)) n += 1
  return `p${n}`
}

export function validatePackages(packages) {
  const ids = packages.map((pkg) => String(pkg.id || '').trim())
  if (ids.some((id) => !id)) return '套餐 ID 不能为空'
  if (ids.some((id) => !/^[A-Za-z0-9_-]+$/.test(id))) return '套餐 ID 仅限字母、数字、下划线和中划线'
  if (new Set(ids).size !== ids.length) return '套餐 ID 不能重复'
  if (packages.some((pkg) => !String(pkg.name || '').trim())) return '套餐名称不能为空'
  if (packages.some((pkg) => !Number.isFinite(pkg.yuan) || pkg.yuan <= 0)) return '套餐金额必须大于 0'
  if (packages.some((pkg) => !Number.isFinite(pkg.bonus_pct) || pkg.bonus_pct < 0 || pkg.bonus_pct > 100)) {
    return '赠送比例必须在 0 到 100 之间'
  }
  return null
}
