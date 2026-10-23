package com.sorghum.traits

import com.sorghum.imaging.PhotoType
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** The catalogue must carry the real IBPGR/ICRISAT (1993) state codes, because Genesys tables use them. */
class TraitCatalogueTest {

    @Test
    fun `midrib colour uses the descriptor's state codes`() {
        val midrib = TraitCatalogue.MIDRIB_COLOUR

        assertEquals(listOf("1", "2", "3", "4", "5", "6"), midrib.stateCodes)
        assertEquals("Dull green", midrib.states[1].label)
        assertEquals(PhotoType.LEAF, midrib.photoType)
        assertEquals(TraitMethod.MEASURED, midrib.method)
    }

    @Test
    fun `grain lustre uses the absent and present codes`() {
        assertEquals(listOf("0", "+"), TraitCatalogue.GRAIN_LUSTRE.stateCodes)
    }

    @Test
    fun `panicle compactness and shape has twelve shapes plus other and is learned`() {
        val panicle = TraitCatalogue.PANICLE_COMPACTNESS_AND_SHAPE

        assertEquals(13, panicle.states.size)
        assertEquals("Broom corn", panicle.states.single { it.code == "12" }.label)
        assertEquals(PhotoType.PANICLE, panicle.photoType)
        assertEquals(TraitMethod.LEARNED, panicle.method)
    }

    @Test
    fun `seed weight is continuous with size classes in grams`() {
        val seedWeight = TraitCatalogue.HUNDRED_SEED_WEIGHT

        assertEquals(PhotoType.GRAIN, seedWeight.photoType)
        val bins = seedWeight.continuousBins!!
        assertEquals(MeasurementUnit.GRAMS, bins.unit)
        assertEquals(seedWeight.states.size - 1, bins.upperEdges.size)
    }

    @Test
    fun `every catalogue trait has a unique id`() {
        val ids = TraitCatalogue.all.map { it.id }

        assertEquals(ids.size, ids.toSet().size)
        assertTrue(ids.size >= 7)
    }

    @Test
    fun `finds a descriptor by id`() {
        assertEquals(TraitCatalogue.GLUME_COLOUR, TraitCatalogue.descriptorFor(TraitCatalogue.GLUME_COLOUR.id))
        assertNull(TraitCatalogue.descriptorFor("awnLength"))
    }

    @Test
    fun `a descriptor refuses duplicate state codes`() {
        assertFailsWith<IllegalArgumentException> {
            TraitDescriptor(
                id = "test",
                name = "Test",
                photoType = PhotoType.LEAF,
                method = TraitMethod.MEASURED,
                states = listOf(DescriptorState("1", "A"), DescriptorState("1", "B")),
            )
        }
    }

    @Test
    fun `a descriptor needs at least two states`() {
        assertFailsWith<IllegalArgumentException> {
            TraitDescriptor("test", "Test", PhotoType.LEAF, TraitMethod.MEASURED, listOf(DescriptorState("1", "A")))
        }
    }

    @Test
    fun `continuous bins must have one edge fewer than the states`() {
        assertFailsWith<IllegalArgumentException> {
            TraitDescriptor(
                id = "test",
                name = "Test",
                photoType = PhotoType.GRAIN,
                method = TraitMethod.MEASURED,
                states = listOf(DescriptorState("3", "Small"), DescriptorState("7", "Large")),
                continuousBins = StateBins(MeasurementUnit.GRAMS, listOf(1.0, 2.0)),
            )
        }
    }

    @Test
    fun `bin edges must increase`() {
        assertFailsWith<IllegalArgumentException> { StateBins(MeasurementUnit.GRAMS, listOf(2.0, 2.0)) }
    }
}
