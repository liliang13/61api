export async function dialogResult(dialog) {
  try {
    return await dialog
  } catch (action) {
    if (action === 'cancel' || action === 'close') return null
    throw action
  }
}
