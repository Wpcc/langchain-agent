import { defineStore } from 'pinia'
import { ref } from 'vue'
import { http } from '@/api/http'

export interface Message {
  role: 'user' | 'assistant'
  content: string
  pending?: boolean
}

export interface Conversation {
  id: string
  title: string
  created_at: string
}

export const useChatStore = defineStore('chat', () => {
  const conversations = ref<Conversation[]>([])
  const currentConvId = ref('')
  const messages = ref<Message[]>([])

  async function fetchConversations() {
    const { data } = await http.get<Conversation[]>('/api/chat/conversations')
    conversations.value = data
  }

  async function createConversation(): Promise<string> {
    const { data } = await http.post<Conversation>('/api/chat/conversations')
    conversations.value.unshift(data)
    return data.id
  }

  async function loadMessages(convId: string) {
    currentConvId.value = convId
    const { data } = await http.get<{ messages: Message[] }>(
      `/api/chat/conversations/${convId}/messages`,
    )
    messages.value = data.messages
  }

  function addMessage(msg: Message) {
    messages.value.push(msg)
  }

  function appendToLastAssistantMessage(chunk: string) {
    const last = messages.value.at(-1)
    if (last?.role === 'assistant') last.content += chunk
  }

  function finalizeLastMessage() {
    const last = messages.value.at(-1)
    if (last) last.pending = false
  }

  async function deleteConversation(convId: string) {
    await http.delete(`/api/chat/conversations/${convId}`)
    conversations.value = conversations.value.filter((c) => c.id !== convId)
    if (currentConvId.value === convId) {
      currentConvId.value = ''
      messages.value = []
    }
  }

  return {
    conversations,
    currentConvId,
    messages,
    fetchConversations,
    createConversation,
    loadMessages,
    addMessage,
    appendToLastAssistantMessage,
    finalizeLastMessage,
    deleteConversation,
  }
})
