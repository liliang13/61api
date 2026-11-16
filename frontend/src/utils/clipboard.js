import { ElMessage } from 'element-plus'

export async function copyText(text, successMessage) {
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success(successMessage)
    return true
  } catch {
    ElMessage.error('复制失败,请检查浏览器剪贴板权限后重试')
    return false
  }
}
