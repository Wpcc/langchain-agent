<template>
  <el-container class="layout">
    <!-- ── Sidebar ── -->
    <el-aside width="260px" class="sidebar">
      <div class="sidebar-top">
        <span class="logo">智扫通客服</span>
        <el-tooltip content="退出登录" placement="right">
          <el-button text @click="handleLogout">
            <el-icon><SwitchButton /></el-icon>
          </el-button>
        </el-tooltip>
      </div>

      <div class="sidebar-body">
        <el-button type="primary" :icon="Plus" class="new-btn" @click="handleNewChat">
          新建对话
        </el-button>

        <div class="conv-list">
          <div
            v-for="conv in chat.conversations"
            :key="conv.id"
            :class="['conv-item', { active: conv.id === chat.currentConvId }]"
            @click="handleSelectConv(conv.id)"
          >
            <el-icon><ChatDotRound /></el-icon>
            <span class="conv-title">{{ conv.title }}</span>
            <el-popconfirm
              title="确认删除此对话？"
              confirm-button-text="删除"
              cancel-button-text="取消"
              confirm-button-type="danger"
              width="160"
              @confirm="handleDeleteConv(conv.id)"
            >
              <template #reference>
                <el-icon class="delete-btn" @click.stop>
                  <Delete />
                </el-icon>
              </template>
            </el-popconfirm>
          </div>
          <div v-if="chat.conversations.length === 0" class="conv-empty">
            暂无对话
          </div>
        </div>
      </div>

      <div class="sidebar-footer">
        <el-tooltip content="知识库管理" placement="right">
          <el-button text class="footer-kb-btn" @click="router.push('/knowledge')">
            <el-icon><Folder /></el-icon>
          </el-button>
        </el-tooltip>
        <el-icon><User /></el-icon>
        <span>{{ auth.username }}</span>
      </div>
    </el-aside>

    <!-- ── Main area ── -->
    <el-main class="main">
      <!-- Active conversation -->
      <template v-if="chat.currentConvId">
        <div class="messages" ref="messagesRef">
          <div v-if="chat.messages.length === 0" class="hint">
            <el-icon size="48" color="#c0c4cc"><ChatLineRound /></el-icon>
            <p>有什么可以帮您的？</p>
          </div>

          <div
            v-for="(msg, idx) in chat.messages"
            :key="idx"
            :class="['row', msg.role]"
          >
            <el-avatar v-if="msg.role === 'user'" :icon="UserFilled" />
            <el-avatar v-else color="#409eff">
              <el-icon><Service /></el-icon>
            </el-avatar>

            <div class="bubble">
              <!-- Waiting for first token: animated typing indicator -->
              <div
                v-if="msg.role === 'assistant' && msg.pending && !msg.content"
                class="typing"
                aria-label="正在思考"
              >
                <span></span><span></span><span></span>
              </div>
              <!-- Streaming / final content (blinking caret while pending) -->
              <div
                v-else
                class="content"
                :class="{ streaming: msg.pending }"
                v-html="toHtml(msg.content)"
              />
            </div>
          </div>
        </div>

        <div class="input-bar">
          <el-input
            v-model="inputText"
            type="textarea"
            :rows="3"
            placeholder="输入消息，Enter 发送，Shift+Enter 换行"
            resize="none"
            :disabled="isSending"
            @keydown.enter.exact.prevent="handleSend"
          />
          <el-button
            type="primary"
            :icon="Promotion"
            :loading="isSending"
            :disabled="!inputText.trim()"
            @click="handleSend"
          >
            发送
          </el-button>
        </div>
      </template>

      <!-- No conversation selected -->
      <div v-else class="welcome">
        <el-icon size="64" color="#c0c4cc"><ChatLineRound /></el-icon>
        <h2>欢迎使用智扫通智能客服</h2>
        <p>点击左侧「新建对话」开始咨询</p>
      </div>
    </el-main>
  </el-container>
</template>

<script setup lang="ts">
import { ref, nextTick, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  Plus, Promotion, UserFilled, Service,
  ChatDotRound, ChatLineRound, SwitchButton, User, Delete, Folder,
} from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { useChatStore } from '@/stores/chat'
import { ChatWebSocket } from '@/api/websocket'

const router = useRouter()
const auth = useAuthStore()
const chat = useChatStore()

const inputText = ref('')
const isSending = ref(false)
const messagesRef = ref<HTMLElement>()
let ws: ChatWebSocket | null = null

onMounted(() => chat.fetchConversations())
onUnmounted(() => ws?.close())

function toHtml(text: string) {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(
      /\[来源[：:]([^\]]+)\]/g,
      '<span class="citation">$1</span>',
    )
    .replace(/\n/g, '<br>')
}

async function scrollToBottom() {
  await nextTick()
  if (messagesRef.value) messagesRef.value.scrollTop = messagesRef.value.scrollHeight
}

async function handleNewChat() {
  const id = await chat.createConversation()
  await selectConv(id)
}

async function handleSelectConv(id: string) {
  if (id === chat.currentConvId) return
  await selectConv(id)
}

async function selectConv(id: string) {
  ws?.close()
  await chat.loadMessages(id)
  connectWs(id)
  await scrollToBottom()
}

function connectWs(convId: string) {
  ws = new ChatWebSocket(convId, auth.token)
  ws.connect(
    (chunk) => { chat.appendToLastAssistantMessage(chunk); scrollToBottom() },
    () => { chat.finalizeLastMessage(); isSending.value = false },
    (err) => { ElMessage.error(err); chat.finalizeLastMessage(); isSending.value = false },
  )
}

async function handleSend() {
  const text = inputText.value.trim()
  if (!text || isSending.value) return
  if (!ws) { ElMessage.error('未连接到服务器，请重新选择对话'); return }

  inputText.value = ''
  isSending.value = true
  chat.addMessage({ role: 'user', content: text })
  chat.addMessage({ role: 'assistant', content: '', pending: true })
  await scrollToBottom()
  ws.send(text)
}

async function handleDeleteConv(id: string) {
  if (id === chat.currentConvId) ws?.close()
  await chat.deleteConversation(id)
}

function handleLogout() {
  ws?.close()
  auth.logout()
  router.push('/login')
}
</script>

<style scoped>
* { box-sizing: border-box; }

.layout { height: 100vh; overflow: hidden; }

/* ── Sidebar ── */
.sidebar {
  display: flex;
  flex-direction: column;
  background: #f5f7fa;
  border-right: 1px solid #e4e7ed;
  overflow: hidden;
}

.sidebar-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px;
  border-bottom: 1px solid #e4e7ed;
  flex-shrink: 0;
}

.logo { font-size: 16px; font-weight: 700; color: #303133; }

.sidebar-body { flex: 1; display: flex; flex-direction: column; overflow: hidden; }

.new-btn { margin: 12px; width: calc(100% - 24px); }

.conv-list { flex: 1; overflow-y: auto; padding: 0 8px 8px; }

.conv-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  color: #606266;
  font-size: 14px;
  transition: background 0.15s;
  overflow: hidden;
}
.conv-item:hover { background: #ebeef5; }
.conv-item.active { background: #ecf5ff; color: #409eff; }
.conv-title { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.conv-empty { text-align: center; color: #c0c4cc; font-size: 13px; padding: 16px 0; }

.delete-btn {
  flex-shrink: 0;
  opacity: 0;
  color: #909399;
  transition: opacity 0.15s, color 0.15s;
}
.conv-item:hover .delete-btn { opacity: 1; }
.delete-btn:hover { color: #f56c6c; }

.sidebar-footer {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  border-top: 1px solid #e4e7ed;
  font-size: 13px;
  color: #909399;
  flex-shrink: 0;
}

.footer-kb-btn {
  margin-right: auto;
  color: #909399;
}

/* ── Main ── */
.main { display: flex; flex-direction: column; padding: 0; overflow: hidden; }

.messages {
  flex: 1;
  overflow-y: auto;
  padding: 24px 20px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.hint, .welcome {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #c0c4cc;
  gap: 10px;
}
.welcome h2 { color: #606266; margin: 0; }
.welcome p { color: #909399; margin: 0; }

.row { display: flex; align-items: flex-start; gap: 12px; }
.row.user { flex-direction: row-reverse; }

.bubble { display: flex; align-items: flex-end; gap: 6px; max-width: 70%; }

.content {
  padding: 12px 16px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.7;
  word-break: break-word;
}
.row.user .content {
  background: #409eff;
  color: #fff;
  border-top-right-radius: 2px;
}
.row.assistant .content {
  background: #f5f7fa;
  color: #303133;
  border-top-left-radius: 2px;
}

/* Typing indicator — shown while waiting for the first token */
.typing {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 14px 16px;
  background: #f5f7fa;
  border-radius: 12px;
  border-top-left-radius: 2px;
}
.typing span {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #c0c4cc;
  animation: typing-bounce 1.4s infinite ease-in-out both;
}
.typing span:nth-child(1) { animation-delay: -0.32s; }
.typing span:nth-child(2) { animation-delay: -0.16s; }
@keyframes typing-bounce {
  0%, 80%, 100% { transform: scale(0.6); opacity: 0.4; }
  40%           { transform: scale(1);   opacity: 1;   }
}

/* Blinking caret appended while tokens are still streaming in */
.content.streaming::after {
  content: '';
  display: inline-block;
  width: 7px;
  height: 1em;
  margin-left: 2px;
  vertical-align: text-bottom;
  background: #909399;
  animation: caret-blink 1s step-end infinite;
}
@keyframes caret-blink { 50% { opacity: 0; } }

.citation {
  display: inline-block;
  margin: 4px 4px 0 0;
  padding: 1px 8px;
  background: #ecf5ff;
  border: 1px solid #b3d8ff;
  border-radius: 4px;
  font-size: 12px;
  color: #409eff;
}

.input-bar {
  padding: 16px;
  border-top: 1px solid #e4e7ed;
  display: flex;
  gap: 12px;
  align-items: flex-end;
  background: #fff;
  flex-shrink: 0;
}
.input-bar .el-button { height: 72px; flex-shrink: 0; }
</style>
