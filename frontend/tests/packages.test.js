import { describe, expect, it } from 'vitest'
import { createPackageId, validatePackages } from '../src/utils/packages'

describe('充值套餐', () => {
  it('按已有套餐生成不重复的顺序短 ID', () => {
    expect(createPackageId([])).toBe('p1')
    expect(createPackageId([{ id: 'p1' }, { id: 'p2' }])).toBe('p3')
    expect(createPackageId([{ id: 'p1' }, { id: 'p3' }])).toBe('p2')
    const grown = [{ id: 'p1' }, { id: 'p2' }, { id: 'p3' }]
    expect(createPackageId(grown)).toBe('p4')
  })

  it('拒绝重复 ID、非法 ID 和无效金额', () => {
    const packages = [
      { id: 'same', name: '套餐一', yuan: 10, bonus_pct: 0 },
      { id: 'same', name: '套餐二', yuan: 20, bonus_pct: 0 },
    ]
    expect(validatePackages(packages)).toBe('套餐 ID 不能重复')
    expect(validatePackages([{ ...packages[0], id: '含 空格' }])).toBe('套餐 ID 仅限字母、数字、下划线和中划线')
    expect(validatePackages([{ ...packages[0], id: 'a'.repeat(40) }])).toBeNull()
    expect(validatePackages([{ ...packages[0], yuan: 0 }])).toBe('套餐金额必须大于 0')
    expect(validatePackages([{ ...packages[0], id: 'valid' }])).toBeNull()
  })
})
