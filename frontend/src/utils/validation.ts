export function isValidEmail(email: string) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())
}

export function isValidPassword(password: string) {
  return password.trim().length >= 8
}

export function isValidPhone(phone: string) {
  const normalized = phone.replace(/\s+/g, "")
  return /^\+?[0-9]{10,15}$/.test(normalized)
}
