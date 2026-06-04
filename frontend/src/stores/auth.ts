import { defineStore } from 'pinia'
import { ref } from 'vue'
import { http } from '@/api/http'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('token') ?? '')
  const username = ref(localStorage.getItem('username') ?? '')

  async function login(name: string, password: string) {
    const { data } = await http.post<{ access_token: string }>('/api/auth/login', {
      username: name,
      password,
    })
    token.value = data.access_token
    username.value = name
    localStorage.setItem('token', token.value)
    localStorage.setItem('username', name)
  }

  async function register(name: string, password: string) {
    await http.post('/api/auth/register', { username: name, password })
  }

  function logout() {
    token.value = ''
    username.value = ''
    localStorage.removeItem('token')
    localStorage.removeItem('username')
  }

  return { token, username, login, register, logout }
})
