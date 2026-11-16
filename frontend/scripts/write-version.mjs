import { writeFileSync } from 'node:fs'

// 构建后写入版本号,供前端检测新版本并自动刷新旧标签页
writeFileSync('dist/version.json', JSON.stringify({ v: Date.now() }))
console.log('version.json written')
