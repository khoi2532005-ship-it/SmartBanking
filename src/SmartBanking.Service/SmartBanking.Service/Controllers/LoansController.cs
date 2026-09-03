using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using Microsoft.AspNetCore.Mvc;
using SmartBanking.Database.Service;

namespace SmartBanking.Service.Controllers
{
    [ApiController]
    [Route("api/[controller]")]
    public class LoansController : ControllerBase
    {
        private readonly IDatabaseClient _db;

        public LoansController(IDatabaseClient db)
        {
            _db = db;
        }

        [HttpGet]
        public async Task<IActionResult> Get([FromQuery] string? customer_id, [FromQuery] string? status)
        {
            var filters = new Dictionary<string, string>();
            if (!string.IsNullOrEmpty(customer_id)) filters["customer_id"] = customer_id;
            if (!string.IsNullOrEmpty(status)) filters["status"] = status;

            var loans = await _db.GetLoansAsync(filters);
            return Ok(loans);
        }

        [HttpGet("{id}")]
        public async Task<IActionResult> GetById(int id)
        {
            var loan = await _db.GetLoanAsync(id);
            if (loan == null) return NotFound();
            return Ok(loan);
        }
    }
}
