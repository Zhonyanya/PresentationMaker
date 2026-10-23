/**
 * Управляющие символы (кроме \t, \n, \r) недопустимы в XML. Они попадают в текст
 * при вставке из Word (\v — мягкий перенос), PDF (\f) и «бинарных» .txt и ломают PPTX.
 */
const INVALID_XML_CHARS = /[\u0000-\u0008\u000b\u000c\u000e-\u001f￾￿]/g

export function sanitizeText(value: string): string {
  // Мягкий перенос Word и разрыв страницы превращаем в обычный перенос строки
  return value.replace(/[\u000b\u000c]/g, '\n').replace(INVALID_XML_CHARS, '')
}
