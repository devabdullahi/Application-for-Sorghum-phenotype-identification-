package com.sorghum.capture.platform

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class BundledSpeciesModelTest {

    @Test
    fun `no model files means no version`() {
        assertNull(highestModelVersion(emptyList()))
        assertNull(highestModelVersion(listOf("images", "webkit", "notes.json")))
    }

    @Test
    fun `picks the highest version by number, not by name`() {
        val names = listOf("traits-v2.json", "traits-v2.tflite", "traits-v10.json", "traits-v9.json")

        assertEquals(10, highestModelVersion(names))
    }

    @Test
    fun `only metadata files count, so a lone tflite is not picked`() {
        assertEquals(1, highestModelVersion(listOf("traits-v1.json", "traits-v3.tflite")))
    }

    @Test
    fun `ignores names that only look like model files`() {
        val names = listOf("traits-v.json", "traits-vX.json", "traits-v4.json.bak", "cultivars-v7.json", "traits-v3.json")

        assertEquals(3, highestModelVersion(names))
    }
}
