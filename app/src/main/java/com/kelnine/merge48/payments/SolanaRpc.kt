package com.kelnine.merge48.payments

import com.solana.networking.HttpNetworkDriver
import com.solana.networking.HttpRequest
import com.solana.networking.Rpc20Driver
import com.solana.rpccore.JsonRpc20Request
import io.ktor.client.HttpClient
import io.ktor.client.engine.android.Android
import io.ktor.client.request.header
import io.ktor.client.request.request
import io.ktor.client.request.setBody
import io.ktor.client.statement.bodyAsText
import io.ktor.http.HttpMethod
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.Serializable
import kotlinx.serialization.builtins.serializer
import kotlinx.serialization.json.add
import kotlinx.serialization.json.addJsonObject
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.put
import java.io.IOException
import java.util.UUID

class KtorHttpDriver : HttpNetworkDriver {
    override suspend fun makeHttpRequest(request: HttpRequest): String =
        HttpClient(Android).use { client ->
            client.request(request.url) {
                method = HttpMethod.parse(request.method)
                request.properties.forEach { (k, v) -> header(k, v) }
                setBody(request.body)
            }.bodyAsText()
        }
}

object SolanaRpc {

    suspend fun latestBlockhash(rpcUrl: String): String = withContext(Dispatchers.IO) {
        val rpc = Rpc20Driver(rpcUrl, KtorHttpDriver())
        val request = JsonRpc20Request(
            "getLatestBlockhash",
            buildJsonArray {
                addJsonObject { put("commitment", "confirmed") }
            },
            UUID.randomUUID().toString()
        )
        val response = rpc.makeRequest(request, BlockhashResponse.serializer())
        response.error?.let { error ->
            throw IOException("getLatestBlockhash failed: ${error.code} ${error.message}")
        }
        response.result?.value?.blockhash
            ?: throw IOException("getLatestBlockhash returned no result")
    }

    suspend fun minimumBalanceForRentExemption(rpcUrl: String, size: Long): Long =
        withContext(Dispatchers.IO) {
            val rpc = Rpc20Driver(rpcUrl, KtorHttpDriver())
            val request = JsonRpc20Request(
                "getMinimumBalanceForRentExemption",
                buildJsonArray { add(size) },
                UUID.randomUUID().toString()
            )
            val response = rpc.makeRequest(request, Long.serializer())
            response.error?.let { error ->
                throw IOException(
                    "getMinimumBalanceForRentExemption failed: ${error.code} ${error.message}"
                )
            }
            response.result
                ?: throw IOException("getMinimumBalanceForRentExemption returned no result")
        }

    @Serializable
    class BlockhashResponse(val value: BlockhashInfo)

    @Serializable
    class BlockhashInfo(val blockhash: String, val lastValidBlockHeight: Long)
}
