package io.github.maximorabyte.swucheckin

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.AtomicFile
import org.json.JSONObject
import java.io.File
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

class Account(val username: String, val password: String) {
    override fun toString(): String = "Account(redacted)"
}

class AccountStorageException : Exception("账号安全存储不可用")

/** Explicit opt-in only. No backup, plaintext fallback, or exported key. */
class SecureAccountStore(context: Context, namespace: String = "account") {
    init { require(namespace.matches(Regex("[a-zA-Z0-9_-]{1,80}"))) }
    private val alias = "${context.packageName}.credentials.v1.$namespace"
    private val aad = alias.toByteArray(Charsets.UTF_8)
    private val file = AtomicFile(File(context.noBackupFilesDir, "$namespace.enc"))

    fun save(account: Account) = synchronized(monitor) {
        try {
            require(account.username.isNotBlank() && account.username.length <= 128)
            require(account.password.isNotEmpty() && account.password.length <= 1024)
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.ENCRYPT_MODE, key(create = true))
            cipher.updateAAD(aad)
            val plain = JSONObject().put("version", 1).put("username", account.username)
                .put("password", account.password).toString().toByteArray(Charsets.UTF_8)
            val encrypted = try { cipher.doFinal(plain) } finally { plain.fill(0) }
            require(cipher.iv.size == 12)
            val stream = file.startWrite()
            try {
                stream.write(byteArrayOf(1))
                stream.write(cipher.iv)
                stream.write(encrypted)
                file.finishWrite(stream)
            } catch (error: Exception) {
                file.failWrite(stream)
                throw error
            }
        } catch (_: Exception) { throw AccountStorageException() }
    }

    fun load(): Account? = synchronized(monitor) {
        try {
            if (!file.baseFile.exists() && !File(file.baseFile.path + ".bak").exists()) return@synchronized null
            val bytes = file.openRead().use { stream ->
                val buffer = ByteArray(16_385)
                var count = 0
                while (count < buffer.size) {
                    val read = stream.read(buffer, count, buffer.size - count)
                    if (read == -1) break
                    count += read
                }
                require(count in 30..16_384)
                buffer.copyOf(count)
            }
            require(bytes[0].toInt() == 1)
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.DECRYPT_MODE, key(create = false), GCMParameterSpec(128, bytes.copyOfRange(1, 13)))
            cipher.updateAAD(aad)
            val plain = cipher.doFinal(bytes.copyOfRange(13, bytes.size))
            val document = try { JSONObject(String(plain, Charsets.UTF_8)) } finally { plain.fill(0) }
            require(document.getInt("version") == 1)
            val account = Account(document.getString("username"), document.getString("password"))
            require(account.username.isNotBlank() && account.username.length <= 128)
            require(account.password.isNotEmpty() && account.password.length <= 1024)
            account
        } catch (_: Exception) { throw AccountStorageException() }
    }

    fun delete() = synchronized(monitor) {
        try {
            file.delete()
            val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
            if (store.containsAlias(alias)) store.deleteEntry(alias)
        } catch (_: Exception) { throw AccountStorageException() }
    }

    private fun key(create: Boolean): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        if (store.containsAlias(alias)) return store.getKey(alias, null) as SecretKey
        check(create)
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
            init(KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setKeySize(256).setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
        }.generateKey()
    }

    companion object { private val monitor = Any() }
}
